from odoo import fields, models


class Exchange(models.Model):
    _name = "dark.rabbit.exchange"
    _description = "Dark Rabbit: Exchange"
    _order = "name ASC"

    connection_id = fields.Many2one(
        comodel_name="dark.rabbit.connection",
        required=True,
        index=True,
        ondelete="cascade",
    )

    name = fields.Char(required=True, index=True)

    exchange_declare = fields.Boolean(string="Declare Exchange")
    exchange_type = fields.Selection(
        selection=[
            ("topic", "Topic"),
            ("direct", "Direct"),
            ("fanout", "Fanout"),
            ("headers", "Headers"),
        ]
    )
    exchange_durable = fields.Boolean()

    active = fields.Boolean(default=True, index=True)

    def _get_exchange_config(self):
        return {
            "name": self.name,
            "declare": self.exchange_declare,
            "type": self.exchange_type,
            "durable": self.exchange_durable,
        }
