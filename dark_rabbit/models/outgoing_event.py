import json

from odoo import api, fields, models


class DarkRabbitOutgoingEvent(models.Model):
    _name = "dark.rabbit.outgoing.event"

    body = fields.Text(required=True, readonly=True)
    body_json_pretty = fields.Text(
        compute="_compute_body_json_pretty", readonly=True, store=False
    )

    outgoing_event_type_id = fields.Many2one(
        comodel_name="dark.rabbit.outgoing.event.type",
        ondelete="set null",
        readonly=True,
    )

    connection_id = fields.Many2one(
        comodel_name="dark.rabbit.connection",
        required=True,
        readonly=True,
        ondelete="restrict",
    )

    exchange = fields.Char(required=True, index=True, readonly=True)

    routing_key = fields.Char(required=True, index=True, readonly=True)

    sent_at = fields.Datetime(readonly=True)

    error = fields.Boolean(readonly=True)
    error_msg = fields.Text(readonly=True)

    # TODO: Replace with create_date
    created_at = fields.Datetime(string="Creation date", automatic=True, readonly=True)

    @api.depends("body")
    def _compute_body_json_pretty(self):
        for record in self:
            try:
                pretty = json.dumps(json.loads(record.body), indent=4)
            except Exception:
                pretty = False
            record.body_json_pretty = pretty

    def add(self, e_type, body):
        event_type = (
            self.sudo()
            .env["dark.rabbit.outgoing.event.type"]
            .search([("code", "=", e_type)])
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
