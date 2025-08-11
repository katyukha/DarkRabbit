from odoo import fields, models


class DarkRabbitQueue(models.Model):
    """This model represents RabbitMQ queue"""

    _name = "dark.rabbit.queue.binding"
    _description = "Dark Rabbit: Queue Binding"
    _order = "queue_id, exchange_name, routing_key"

    queue_id = fields.Many2one(
        comodel_name="dark.rabbit.queue",
        required=True,
        index=True,
    )
    exchange_name = fields.Char(required=True, index=True)
    routing_key = fields.Char()
