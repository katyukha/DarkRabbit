from odoo import fields, models


class DarkRabbitOutgoingEventType(models.Model):
    _name = "dark.rabbit.outgoing.event.type"

    _inherit = ["generic.mixin.name_with_code", "generic.mixin.uniq_name_code"]

    sequence = fields.Integer(index=True)

    outgoing_routing_ids = fields.One2many(
        comodel_name="dark.rabbit.outgoing.routing",
        inverse_name="outgoing_event_type_id",
        string="Outgoing routing",
    )
