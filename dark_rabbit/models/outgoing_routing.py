from odoo import fields, models


class DarkRabbitOutgoingRouting(models.Model):
    _name = "dark.rabbit.outgoing.routing"
    _description = "Dark Rabbit Outgoing Routing"

    outgoing_event_type_id = fields.Many2one(
        comodel_name="dark.rabbit.outgoing.event.type",
        string="Outgoing event type",
        required=True,
        index=True,
        ondelete="cascade",
    )

    connection_id = fields.Many2one(
        comodel_name="dark.rabbit.connection",
        string="Connection",
        ondelete="cascade",
        required=True,
        index=True,
    )

    exchange_id = fields.Many2one("dark.rabbit.exchange", required=True, index=True)
    exchange = fields.Char(
        string="Exchange",
        related="exchange_id.name",
        required=False,
        index=False,
        readonly=True,
        store=True,
    )
    require_tag_id = fields.Many2one(
        comodel_name="dark.rabbit.outgoing.routing.tag", index=True
    )
    require_tag_code = fields.Char(
        related="require_tag_id.code", store=True, index=True, readonly=True
    )

    routing_key = fields.Char(string="Routing Key", required=True, index=True)

    active = fields.Boolean(default=True, index=True)

    _conn_type_exch_route_unique = models.Constraint(
        "UNIQUE(outgoing_event_type_id, connection_id, exchange_id, routing_key)",
        "The outgoing routing must be unique!",
    )
