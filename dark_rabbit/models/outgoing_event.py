from odoo import fields, models


class DarkRabbitOutgoingEvent(models.Model):
    _name = "dark.rabbit.outgoing.event"

    body = fields.Text(required=True, string="Outgoing event body")

    outgoing_event_type_id = fields.Many2one(
        comodel_name="dark.rabbit.outgoing.event.type", string="Оutgoing event type"
    )

    sent_at = fields.Datetime(string="Sent date")

    creted_at = fields.Datetime(string="Creation date", automatic=True, readonly=True)
