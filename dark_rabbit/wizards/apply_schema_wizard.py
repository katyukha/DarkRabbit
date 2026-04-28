import logging

from odoo import _, fields, models
from odoo.exceptions import UserError

from ..tools.rabbit_schema_spec import (
    RabbitSchemaSpec,
    SchemaConflictError,
    merge,
    parse_yaml,
)

_logger = logging.getLogger(__name__)


class ApplySchemaWizard(models.TransientModel):
    _name = "dark.rabbit.apply.schema.wizard"
    _description = "Dark Rabbit: Apply Schema to Connection"

    connection_id = fields.Many2one(
        comodel_name="dark.rabbit.connection",
        required=True,
        string="Connection",
    )
    schema_ids = fields.Many2many(
        comodel_name="dark.rabbit.schema",
        string="Schemas",
    )

    def action_apply(self):
        self.ensure_one()

        if not self.schema_ids:
            raise UserError(_("Select at least one schema to apply."))

        specs = []
        for schema in self.schema_ids:
            try:
                specs.append(parse_yaml(schema.spec or ""))
            except ValueError as exc:
                raise UserError(
                    _("Schema %(name)s: %(error)s", name=schema.name, error=exc)
                ) from exc

        try:
            merged = merge(specs)
        except SchemaConflictError as exc:
            raise UserError(str(exc)) from exc

        self._reconcile(self.connection_id, merged)

        return {"type": "ir.actions.act_window_close"}

    def _reconcile(self, connection, spec: RabbitSchemaSpec):
        """Reconcile merged spec against existing DB records on the connection.

        Creates missing entities and updates drifted fields.  Bindings are
        additive — existing bindings are never removed.

        Exchanges are processed before queues so DLX references can be
        resolved within the same apply.
        """
        Exchange = self.env["dark.rabbit.exchange"]
        Queue = self.env["dark.rabbit.queue"]
        Binding = self.env["dark.rabbit.queue.binding"]

        # --- exchanges ---
        for ex_spec in spec.exchanges.values():
            exchange = Exchange.search(
                [
                    ("connection_id", "=", connection.id),
                    ("name", "=", ex_spec.name),
                ],
                limit=1,
            )
            vals = {
                "exchange_declare": ex_spec.declare,
                "exchange_type": ex_spec.type,
                "exchange_durable": ex_spec.durable,
            }
            if not exchange:
                Exchange.create(
                    dict(vals, connection_id=connection.id, name=ex_spec.name)
                )
            else:
                exchange.write(vals)

        # --- queues ---
        for q_spec in spec.queues.values():
            queue = Queue.search(
                [
                    ("connection_id", "=", connection.id),
                    ("queue_name", "=", q_spec.name),
                ],
                limit=1,
            )
            vals = {
                "queue_declare": q_spec.declare,
                "queue_declare_durable": q_spec.durable,
                "queue_declare_exclusive": q_spec.exclusive,
                "queue_declare_auto_delete": q_spec.auto_delete,
            }
            if q_spec.dlx:
                dlx = Exchange.search(
                    [
                        ("connection_id", "=", connection.id),
                        ("name", "=", q_spec.dlx),
                    ],
                    limit=1,
                )
                if not dlx:
                    raise UserError(
                        _(
                            "Queue %(queue)s references DLX exchange %(dlx)s "
                            "which does not exist on this connection. "
                            "Add it to a schema and apply.",
                            queue=q_spec.name,
                            dlx=q_spec.dlx,
                        )
                    )
                vals["queue_declare_dlx_id"] = dlx.id
            if q_spec.dlq_routing:
                vals["queue_declare_dlq_routing"] = q_spec.dlq_routing

            if not queue:
                queue = Queue.create(
                    dict(
                        vals,
                        connection_id=connection.id,
                        queue_name=q_spec.name,
                    )
                )
            else:
                queue.write(vals)

            # --- bindings ---
            for b_spec in q_spec.bindings:
                exchange = Exchange.search(
                    [
                        ("connection_id", "=", connection.id),
                        ("name", "=", b_spec.exchange),
                    ],
                    limit=1,
                )
                if not exchange:
                    raise UserError(
                        _(
                            "Queue %(queue)s binding references exchange "
                            "%(exchange)s which does not exist on this "
                            "connection. Add it to a schema and apply.",
                            queue=q_spec.name,
                            exchange=b_spec.exchange,
                        )
                    )
                exists = Binding.search(
                    [
                        ("queue_id", "=", queue.id),
                        ("exchange_id", "=", exchange.id),
                        ("routing_key", "=", b_spec.routing_key),
                    ],
                    limit=1,
                )
                if not exists:
                    Binding.create(
                        {
                            "queue_id": queue.id,
                            "exchange_id": exchange.id,
                            "routing_key": b_spec.routing_key,
                        }
                    )
