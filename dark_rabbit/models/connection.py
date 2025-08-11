import logging
import urllib.parse

from odoo import api, fields, models

from odoo.addons.generic_mixin.tools.x2m_agg_utils import read_counts_for_o2m

_logger = logging.getLogger(__name__)

try:
    import pika
except (OSError, ImportError):
    _logger.error("Cannot import py-package 'pika'")


class DarkRabbitConnection(models.Model):
    _name = "dark.rabbit.connection"
    _inherit = [
        "generic.mixin.name_with_code",
        "generic.mixin.uniq_name_code",
    ]
    _order = "name"

    name = fields.Char(required=True, index=True)
    code = fields.Char()

    host = fields.Char(required=True)
    port = fields.Integer(default=5672, required=True)
    virtual_host = fields.Char(default="/", required=True)

    user = fields.Char()
    password = fields.Char()

    queue_ids = fields.One2many(
        comodel_name="dark.rabbit.queue", inverse_name="connection_id"
    )
    queue_count = fields.Integer(compute="_compute_queue_count", readonly=True)
    event_ids = fields.One2many(
        comodel_name="dark.rabbit.event", inverse_name="connection_id"
    )
    event_count = fields.Integer(compute="_compute_event_count", readonly=True)

    active = fields.Boolean(default=True, index=True)

    @api.depends("queue_ids")
    def _compute_queue_count(self):
        mapped_data = read_counts_for_o2m(
            records=self, field_name="queue_ids", sudo=True
        )
        for rec in self:
            rec.queue_count = mapped_data.get(rec.id, 0)

    @api.depends("event_ids")
    def _compute_event_count(self):
        mapped_data = read_counts_for_o2m(
            records=self, field_name="event_ids", sudo=True
        )
        for rec in self:
            rec.event_count = mapped_data.get(rec.id, 0)

    def get_connection_url(self):
        self.ensure_one()

        return (
            f"amqp://{self.user}:{self.password}@{self.host}:{self.port}/"
            f"{urllib.parse.quote_plus(self.virtual_host)}"
        )

    def get_consumer_config(self):
        """Return consumer config for background worker"""
        self.ensure_one()
        return {
            "connection_id": self.id,
            "connection_url": self.get_connection_url(),
            "listen_queues": [q.get_queue_config() for q in self.queue_ids if q.listen],
        }

    def get_connection(self):
        self.ensure_one()

        try:
            connection = pika.BlockingConnection(
                pika.URLParameters(self.get_connection_url())
            )
        except Exception:
            _logger.error(
                "DarkRabbit [%s (%s)]: Connection Error!",
                self.name,
                self.get_connection_url(),
                exc_info=True,
            )
            raise

        return connection

    def action_test_connection(self):
        self.ensure_one()

        with self.get_connection():
            _logger.info("Connection successful")

    def action_view_queues(self):
        self.ensure_one()
        return self.env["generic.mixin.get.action"].get_action_by_xmlid(
            "dark_rabbit.action_dark_rabbit_queue_list",
            domain=[("connection_id", "=", self.id)],
            context={"default_connection_id": self.id},
        )

    def action_view_events(self):
        self.ensure_one()
        return self.env["generic.mixin.get.action"].get_action_by_xmlid(
            "dark_rabbit.action_dark_rabbit_event_list",
            domain=[("connection_id", "=", self.id)],
        )
