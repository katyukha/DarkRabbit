import json
import logging
import time
from typing import List

from odoo import api, fields, models

from odoo.addons.base_field_big_int import BigInt

_logger = logging.getLogger(__name__)


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
        index=True,
    )

    exchange = fields.Char(required=True, index=True, readonly=True)

    routing_key = fields.Char(required=True, index=True, readonly=True)
    message_id = fields.Char(
        index="btree_not_null",
        required=True,
        readonly=True,
        size=38,
        default="/",
        copy=False,
        string="Message Id",
    )
    correlation_id = fields.Char(
        index="btree_not_null",
        readonly=True,
        string="Correlation ID",
        help="Correlation ID for message properties.",
    )
    timestamp = BigInt(
        index=True, readonly=True, help="Timestamp for message properties"
    )
    message_type = fields.Char(readonly=True, help="Type field for message properties")
    content_type = fields.Char(readonly=True, help="Content type of incoming message")

    sent_at = fields.Datetime(index=True, readonly=True)

    error = fields.Boolean(readonly=True)
    error_msg = fields.Text(readonly=True)

    # TODO: Replace with create_date
    created_at = fields.Datetime(
        default=fields.Datetime.now,
        string="Creation date",
        readonly=True,
        index=True,
    )

    @api.depends("body")
    def _compute_body_json_pretty(self):
        for record in self:
            try:
                pretty = json.dumps(json.loads(record.body), indent=4)
            except Exception:
                pretty = False
            record.body_json_pretty = pretty

    def init(self):
        self.env.cr.execute(
            """
            -- Index used by event sender to search for new events to be sent.
            CREATE INDEX IF NOT EXISTS dark_rabbit_outgoing_event__sender_search__idx
                 ON dark_rabbit_outgoing_event ("created_at", "timestamp", "id")
                 WHERE sent_at IS NULL;
            """
        )
        return super().init()

    def add(
        self,
        e_type,
        body,
        correlation_id=None,
        jsonify=True,
        tags: List[str] | str = None,
    ):
        if tags and isinstance(tags, str):
            tags = [tags]
        tags = tags if tags else []

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

        for route in event_type.outgoing_routing_ids:
            if route.require_tag_code and route.require_tag_code not in tags:
                # This route require tag but event does not have required tag,
                # thus we skip this route.
                continue

            self.sudo().env["dark.rabbit.outgoing.event"].create(
                dict(
                    event_data,
                    connection_id=route.connection_id.id,
                    exchange=route.exchange,
                    routing_key=route.routing_key,
                )
            )
