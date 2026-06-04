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

    exchange_id = fields.Many2one("dark.rabbit.exchange", required=True, index=True)
    exchange_name = fields.Char(
        string="Exchange",
        related="exchange_id.name",
        required=False,
        index=False,
        readonly=True,
        store=False,
    )
    routing_key = fields.Char()
    bind = fields.Boolean(default=True)

    _sql_constraints = [
        (
            "unique_queue_exchange_routing_key",
            "UNIQUE NULLS NOT DISTINCT (queue_id, exchange_id, routing_key)",
            "A binding for this queue, exchange, and routing key already exists.",
        )
    ]
