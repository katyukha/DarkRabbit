from odoo import fields, models


class DarkRabbitOutgoingRouting(models.Model):
    _name = "dark.rabbit.outgoing.routing"
    _inherit = [
        "generic.mixin.name_with_code",
        "generic.mixin.uniq_name_code",
    ]

    outgoing_event_type_id = fields.Many2one(
        comodel_name="dark.rabbit.outgoing.event.type",
        inverse_name="outgoing_routing_ids",
        string="Outgoing event type",
        required=True,
    )

    connection_id = fields.Many2one(
        comodel_name="dark.rabbit.connection", string="Connection", ondelete="set null"
    )

    exchange = fields.Char(string="Exchange", required=True, index=True)

    routing_key = fields.Char(string="Routing Key", required=True, index=True)

    active = fields.Boolean(default=True, index=True)

    creted_at = fields.Datetime(string="Creation date", automatic=True, readonly=True)
