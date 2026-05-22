import json
import logging
import traceback

from odoo import api, fields, models

from odoo.addons.base_field_big_int import BigInt

_logger = logging.getLogger(__name__)


class DarkRabbitEvent(models.Model):
    _name = "dark.rabbit.event"
    _description = "Dark Rabbit: Event"
    _order = "create_date DESC, timestamp DESC"

    create_date = fields.Datetime(required=True, index=True, readonly=True)
    message_id = fields.Char(
        string="Message ID",
        index="btree_not_null",
        readonly=True,
        help="Message ID from message properties",
    )
    correlation_id = fields.Char(
        string="Correlation ID",
        readonly=True,
        index="btree_not_null",
        help="Correlation ID from message properties.",
    )
    timestamp = BigInt(
        index=True, readonly=True, help="Timestamp from message properties"
    )
    message_type = fields.Char(readonly=True, help="Type field from message properties")
    content_type = fields.Char(readonly=True, help="Content type of incoming message")
    connection_id = fields.Many2one(
        comodel_name="dark.rabbit.connection",
        required=True,
        index=True,
        ondelete="restrict",
        readonly=True,
    )
    queue_id = fields.Many2one(
        comodel_name="dark.rabbit.queue",
        required=True,
        index=True,
        readonly=True,
        ondelete="restrict",
    )
    handler_id = fields.Many2one(
        comodel_name="dark.rabbit.handler", required=False, readonly=True, index=True
    )
    routing_key = fields.Char(required=True, readonly=True)
    body = fields.Text(readonly=True)
    body_json_pretty = fields.Text(
        compute="_compute_body_json_pretty", readonly=True, store=False
    )

    error = fields.Boolean(readonly=True)
    error_msg = fields.Text(readonly=True)

    @api.depends("body")
    def _compute_body_json_pretty(self):
        for record in self:
            try:
                pretty = json.dumps(
                    json.loads(record.body), indent=4, ensure_ascii=False
                )
            except Exception:
                pretty = False
            record.body_json_pretty = pretty

    def init(self):
        super().init()
        self.env.cr.execute(
            """
            CREATE INDEX IF NOT EXISTS dark_rabbit_event__error__idx
            ON dark_rabbit_event (id)
            WHERE error = True
        """
        )

    @api.model
    def handle_message(self, message):
        # Message is DarkRabbitMessage
        # TODO: Use SQL to ensure connect, queue and handler_id still exists
        # TODO: Avoid duplication, if message_id is available

        event = self.create(
            {
                "connection_id": message.connection_id,
                "queue_id": message.queue_id,
                "routing_key": message.method.routing_key,
                "handler_id": message.handler_id,
                "body": message.body,
                "correlation_id": message.properties.correlation_id,
                "message_id": message.properties.message_id,
                "message_type": message.properties.type,
                "timestamp": message.properties.timestamp,
                "content_type": message.properties.content_type,
            }
        )

        if event.handler_id:
            try:
                with self.env.cr.savepoint():
                    event.handler_id._dark_rabbit_handle_event(event)
            except Exception as exc:
                _logger.error("Cannot handle message %s", message, exc_info=True)
                with self.env.cr.savepoint():
                    event.write(
                        {
                            "error": True,
                            "error_msg": "".join(traceback.format_exception(exc)),
                        }
                    )

    def action_retry_handle(self):
        """Run event handler one more time for events that has handler defined"""
        for record in self.search(
            [("id", "in", self.ids)], order="timestamp ASC, id ASC"
        ):
            if record.handler_id:
                record.handler_id._dark_rabbit_handle_event(record)
                record.write(
                    {
                        "error": False,
                        "error_msg": False,
                    }
                )

    def read_as_json(self):
        return json.loads(self.body)
