from odoo import fields, models

from odoo.addons.dark_rabbit import dark_rabbit_handler


class TestDarkRabbitHandler(models.Model):
    _name = "test.dark.rabbit.handler"
    _inherit = "dark.rabbit.handler.mixin"

    body = fields.Text()

    @dark_rabbit_handler("Test Handler")
    def _on_dark_rabbit_event(self, event):
        self.create({"body42": event.body})
