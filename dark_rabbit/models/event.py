import traceback
import logging

from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class DarkRabbitEvent(models.Model):
    _name = 'dark.rabbit.event'
    _order = 'create_date DESC'

    create_date = fields.Datetime(required=True, index=True)
    connection_id = fields.Many2one(
        comodel_name='dark.rabbit.connection',
        required=True, index=True,
        ondelete='restrict')
    queue_id = fields.Many2one(
        comodel_name='dark.rabbit.queue',
        required=True, index=True,
        ondelete='restrict')
    handler_id = fields.Many2one(
        comodel_name='dark.rabbit.handler',
        required=False, index=True)
    routing_key = fields.Char(required=True)
    body = fields.Text()

    error = fields.Boolean(readonly=True)
    error_msg = fields.Text(readonly=True)

    @api.model
    def handle_message(self, message):
        # Message is DarkRabbitMessage
        # TODO: Use SQL to ensure connect, queue and handler_id still exists
        event = self.create({
            'connection_id': message.connection_id,
            'queue_id': message.queue_id,
            'routing_key': message.method.routing_key,
            'handler_id': message.handler_id,
            'body': message.body,
        })

        if event.handler_id:
            try:
                with self.env.cr.savepoint():
                    event.handler_id._dark_rabbit_handle_event(event)
            except Exception as exc:
                _logger.error("Cannot handle message %s", message, exc_info=True)
                with self.env.cr.savepoint():
                    event.write({
                        'error': True,
                        'error_msg': "".join(traceback.format_exception(exc)),
                    })
