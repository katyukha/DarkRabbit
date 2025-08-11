from odoo import fields, models


class DarkRabbitHandler(models.Model):
    """This model stores information about defined handlers,
    capable of handling messages received from DarkRabbit
    """

    _name = "dark.rabbit.handler"
    _description = "Dark Rabbit: Handler"

    name = fields.Char(required=True, index=True, readonly=True)
    model_id = fields.Many2one(
        comodel_name="ir.model",
        required=True,
        index=True,
        readonly=True,
        ondelete="cascade",
        help="Model that can handle events from dark rabbit",
    )
    method_name = fields.Char(
        required=True, readonly=True, help="Name of method to call to handle event"
    )

    _sql_constraints = [
        (
            "model_method_uniq",
            "UNIQUE(model_id, method_name)",
            "Handler's model and method must be unique",
        ),
    ]

    def _dark_rabbit_handle_event(self, event):
        model = self.sudo().env[self.model_id.model]
        method = getattr(model, self.method_name)
        return method(event)
