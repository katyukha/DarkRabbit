from odoo import fields, models


class DarkRabbitOutgoingEvent(models.Model):
    _name = "dark.rabbit.outgoing.event"

    body = fields.Text(required=True)

    outgoing_event_type_id = fields.Many2one(
        comodel_name="dark.rabbit.outgoing.event.type"
    )

    connection_id = fields.Many2one(
        comodel_name="dark.rabbit.connection", required=True
    )

    exchange = fields.Char(required=True, index=True)

    routing_key = fields.Char(required=True, index=True)

    sent_at = fields.Datetime()

    error = fields.Boolean(readonly=True)
    error_msg = fields.Text(readonly=True)

    creted_at = fields.Datetime(string="Creation date", automatic=True, readonly=True)

    def add(self, e_type, body):
        event_type = self.env["dark.rabbit.outgoing.event.type"].search(
            [("code", "=", e_type)]
        )
        routing_ids = event_type.outgoing_routing_ids

        for routing_id in routing_ids:
            self.sudo().env["dark.rabbit.outgoing.event"].create(
                {
                    "body": body,
                    "outgoing_event_type_id": event_type.id,
                    "connection_id": routing_id.connection_id.id,
                    "exchange": routing_id.exchange,
                    "routing_key": routing_id.routing_key,
                }
            )
