import json
import time

from odoo import api, fields, models


class DarkRabbitOutgoingEvent(models.Model):
    _name = "dark.rabbit.outgoing.event"
    _inherit = [
        "generic.mixin.uuid",
    ]
    _order = "created_at DESC"
    _description = "Dark Rabbit Outgoing Event"

    _generic_mixin_uuid_field_name = "message_id"

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
    message_id = fields.Char(
        index=True,
        required=True,
        readonly=True,
        size=38,
        default="/",
        copy=False,
        string="Message Id",
    )
    correlation_id = fields.Char(
        readonly=True,
        string="Correlation ID",
        help="Correlation ID for message properties.",
    )
    timestamp = fields.Char(readonly=True, help="Timestamp for message properties")
    message_type = fields.Char(readonly=True, help="Type field for message properties")
    content_type = fields.Char(readonly=True, help="Content type of incoming message")

    sent_at = fields.Datetime(readonly=True)

    error = fields.Boolean(readonly=True)
    error_msg = fields.Text(readonly=True)

    # TODO: Replace with create_date
    created_at = fields.Datetime(
        default=fields.Datetime.now,
        string="Creation date",
        automatic=True,
        readonly=True,
    )

    @api.depends("body")
    def _compute_body_json_pretty(self):
        for record in self:
            try:
                pretty = json.dumps(json.loads(record.body), indent=4)
            except Exception:
                pretty = False
            record.body_json_pretty = pretty

    def add(self, e_type, body, correlation_id=None, jsonify=True):
        event_type = (
            self.sudo()
            .env["dark.rabbit.outgoing.event.type"]
            .search([("code", "=", e_type)])
        )

        event_data = {
            "message_type": event_type.code,
            "timestamp": int(round(time.time() * 1000)),  # timestamp in miliseconds
            "outgoing_event_type_id": event_type.id,
        }
        if correlation_id is not None:
            event_data["correlation_id"] = correlation_id
        if jsonify:
            event_data["body"] = json.dumps(body)
            event_data["content_type"] = "application/json"
        else:
            event_data["body"] = body
            event_data["content_type"] = "text/plain"

        for routing_id in event_type.outgoing_routing_ids:
            self.sudo().env["dark.rabbit.outgoing.event"].create(
                dict(
                    event_data,
                    connection_id=routing_id.connection_id.id,
                    exchange=routing_id.exchange,
                    routing_key=routing_id.routing_key,
                )
            )
