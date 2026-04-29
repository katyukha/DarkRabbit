from odoo import api, fields, models


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
    model_name = fields.Char(
        related="model_id.model",
        store=True,
        readonly=True,
        index=True,
        string="Model Name",
    )
    method_name = fields.Char(
        required=True, readonly=True, help="Name of method to call to handle event"
    )
    handler_code = fields.Char(
        compute="_compute_handler_code",
        store=True,
        readonly=True,
        index=True,
        string="Handler Code",
        help="Unique identifier in the form model.name:method_name, "
        "used to reference this handler in schema YAML.",
    )

    _sql_constraints = [
        (
            "model_method_uniq",
            "UNIQUE(model_id, method_name)",
            "Handler's model and method must be unique",
        ),
        (
            "handler_code_uniq",
            "UNIQUE(handler_code)",
            "Handler code must be unique",
        ),
    ]

    @api.depends("model_id.model", "method_name")
    def _compute_handler_code(self):
        for rec in self:
            if rec.model_id and rec.method_name:
                rec.handler_code = f"{rec.model_id.model}:{rec.method_name}"
            else:
                rec.handler_code = False

    def _dark_rabbit_handle_event(self, event):
        model = self.sudo().env[self.model_id.model]
        method = getattr(model, self.method_name)
        return method(event)
