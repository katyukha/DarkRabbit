from odoo.tools import sql


def migrate(cr, version):
    if sql.table_exists(cr, "dark_rabbit_exchange"):
        # There is no need to run migration. table for exchanges already created
        return

    sql.create_model_table(
        cr,
        "dark_rabbit_exchange",
        comment=None,
        columns=[
            ("connection_id", "int4", None),
            ("name", "varchar", None),
            ("exchange_declare", "bool", None),
            ("exchange_type", "varchar", None),
            ("exchange_durable", "bool", None),
        ],
    )
    sql.create_column(cr, "dark_rabbit_queue_binding", "exchange_id", "int4")
    sql.create_column(cr, "dark_rabbit_queue", "queue_declare_dlx_id", "int4")
    sql.create_column(cr, "dark_rabbit_queue", "queue_declare_dlq_id", "int4")
    sql.create_column(cr, "dark_rabbit_outgoing_routing", "exchange_id", "int4")

    # Create DLX exchanges
    cr.execute(
        """
        INSERT INTO dark_rabbit_exchange
            (connection_id, name, exchange_declare, exchange_type, exchange_durable)
        SELECT connection_id, queue_declare_dlx, True, 'direct', True
        FROM dark_rabbit_queue AS drq
        WHERE queue_declare_dlx IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM dark_rabbit_exchange AS dre
            WHERE dre.name = drq.queue_declare_dlx
            AND dre.connection_id = drq.connection_id
          );
    """
    )

    # Create exchanges from bindings
    cr.execute(
        """
        INSERT INTO dark_rabbit_exchange
            (connection_id, name)
        SELECT DISTINCT drq.connection_id, drqb.exchange_name
        FROM dark_rabbit_queue_binding AS drqb
        LEFT JOIN dark_rabbit_queue AS drq ON drq.id = drqb.queue_id
        WHERE NOT EXISTS (
            SELECT 1 FROM dark_rabbit_exchange AS dre
            WHERE dre.name = drqb.exchange_name
            AND dre.connection_id = drq.connection_id
        );
    """
    )

    # Create exchanges from outgoing routings
    cr.execute(
        """
        INSERT INTO dark_rabbit_exchange
            (connection_id, name)
        SELECT DISTINCT dror.connection_id, dror.exchange
        FROM dark_rabbit_outgoing_routing AS dror
        WHERE NOT EXISTS (
            SELECT 1 FROM dark_rabbit_exchange AS dre
            WHERE dre.name = dror.exchange
            AND dre.connection_id = dror.connection_id
        );
    """
    )

    # Update queue bindings
    cr.execute(
        """
        UPDATE dark_rabbit_queue_binding AS drqb
        SET exchange_id = (SELECT id FROM dark_rabbit_exchange WHERE name = drqb.exchange_name)
    """
    )

    # Update outgoing routings
    cr.execute(
        """
        UPDATE dark_rabbit_outgoing_routing AS dror
        SET exchange_id = (SELECT id FROM dark_rabbit_exchange WHERE name = dror.exchange)
    """
    )

    # Create and configure missing DLQs
    cr.execute(
        """
        INSERT INTO dark_rabbit_queue
            (connection_id, queue_name, queue_declare, queue_declare_durable, active)
        SELECT connection_id, queue_declare_dlq, True, True, True
        FROM dark_rabbit_queue AS drq
        WHERE NOT EXISTS (
            SELECT 1 FROM dark_rabbit_queue AS drq_1
            WHERE drq_1.queue_name = drq.queue_declare_dlq
              AND drq_1.connection_id = drq.connection_id
        );

        UPDATE dark_rabbit_queue AS drq
        SET queue_declare_dlx_id = (
               SELECT id
               FROM dark_rabbit_exchange
               WHERE connection_id = drq.connection_id AND name = drq.queue_declare_dlx),
            queue_declare_dlq_id = (
               SELECT id
               FROM dark_rabbit_queue
               WHERE connection_id = drq.connection_id AND queue_name = drq.queue_declare_dlq);

        INSERT INTO dark_rabbit_queue_binding
            (queue_id, exchange_id, exchange_name, routing_key)
        SELECT drq.queue_declare_dlq_id,
               drq.queue_declare_dlx_id,
               drq.queue_declare_dlx,
               drq.queue_declare_dlq_routing
        FROM dark_rabbit_queue AS drq
        WHERE drq.queue_declare_dlq_id IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM dark_rabbit_queue_binding AS drqb
            WHERE drqb.queue_id = drq.id
              AND drqb.exchange_name = drq.queue_declare_dlx
        )
    """
    )
