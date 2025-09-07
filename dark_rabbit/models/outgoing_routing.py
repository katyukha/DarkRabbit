from odoo import fields, models


class DarkRabbitOutgoingRouting(models.Model):
    _name = "dark.rabbit.outgoing.routing"
    _description = "Dark Rabbit Outgoing Routing"

    outgoing_event_type_id = fields.Many2one(
        comodel_name="dark.rabbit.outgoing.event.type",
        string="Outgoing event type",
        required=True,
        index=True,
    )

    connection_id = fields.Many2one(
        comodel_name="dark.rabbit.connection",
        string="Connection",
        ondelete="cascade",
        required=True,
        index=True,
    )

    exchange = fields.Char(string="Exchange", required=True, index=True)

    routing_key = fields.Char(string="Routing Key", required=True, index=True)

    active = fields.Boolean(default=True, index=True)

    _sql_constraints = [
        (
            "conn_type_exch_route_unique",
            "UNIQUE(outgoing_event_type_id, connection_id, exchange, routing_key)",
            "The outgoing routing must be unique!",
        ),
    ]
