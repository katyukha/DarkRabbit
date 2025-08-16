import json
import logging
import traceback

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class DarkRabbitEvent(models.Model):
    _name = "dark.rabbit.event"
    _description = "Dark Rabbit: Event"
    _order = "create_date DESC"

    create_date = fields.Datetime(required=True, index=True)
    connection_id = fields.Many2one(
        comodel_name="dark.rabbit.connection",
        required=True,
        index=True,
        ondelete="restrict",
    )
    queue_id = fields.Many2one(
        comodel_name="dark.rabbit.queue", required=True, index=True, ondelete="restrict"
    )
    handler_id = fields.Many2one(
        comodel_name="dark.rabbit.handler", required=False, index=True
    )
    routing_key = fields.Char(required=True)
    body = fields.Text()
    body_json_pretty = fields.Text(
        compute="_compute_body_json_pretty", readonly=True, store=False
    )

    error = fields.Boolean(readonly=True)
    error_msg = fields.Text(readonly=True)

    @api.depends("body")
    def _compute_body_json_pretty(self):
        for record in self:
            try:
                pretty = json.dumps(json.loads(record.body), indent=4)
            except Exception:
                pretty = False
            record.body_json_pretty = pretty

    @api.model
    def handle_message(self, message):
        # Message is DarkRabbitMessage
        # TODO: Use SQL to ensure connect, queue and handler_id still exists
        event = self.create(
            {
                "connection_id": message.connection_id,
                "queue_id": message.queue_id,
                "routing_key": message.method.routing_key,
                "handler_id": message.handler_id,
                "body": message.body,
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
        for record in self:
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
