from odoo import fields, models


class DarkRabbitOutgoingRoutingTag(models.Model):
    """This model implements routing tags,
    that could be used to dispatch events,
    to decide what event routing to use.
    """

    _name = "dark.rabbit.outgoing.routing.tag"
    _description = "Dark Rabbit: Outgoing Routing Tag"
    _inherit = [
        "generic.mixin.name_with_code",
    ]

    name = fields.Char()
    code = fields.Char()
