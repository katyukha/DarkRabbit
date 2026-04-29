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
    _description = "Dark Rabbit Connection"

    host = fields.Char(required=True)
    port = fields.Integer(default=5672, required=True)
    virtual_host = fields.Char(default="/", required=True)

    user = fields.Char()
    password = fields.Char()

    queue_ids = fields.One2many(
        comodel_name="dark.rabbit.queue", inverse_name="connection_id"
    )
    queue_count = fields.Integer(compute="_compute_queue_count", readonly=True)
    exchange_ids = fields.One2many(
        comodel_name="dark.rabbit.exchange", inverse_name="connection_id"
    )
    exchange_count = fields.Integer(compute="_compute_exchange_count", readonly=True)
    event_ids = fields.One2many(
        comodel_name="dark.rabbit.event", inverse_name="connection_id"
    )
    event_count = fields.Integer(compute="_compute_event_count", readonly=True)

    outgoing_route_ids = fields.One2many(
        comodel_name="dark.rabbit.outgoing.routing",
        inverse_name="connection_id",
    )
    outgoing_route_count = fields.Integer(
        compute="_compute_outgoing_route_count",
        readonly=True,
    )

    outgoing_event_ids = fields.One2many(
        comodel_name="dark.rabbit.outgoing.event",
        inverse_name="connection_id",
    )
    outgoing_event_count = fields.Integer(
        compute="_compute_outgoing_event_count",
        readonly=True,
    )
    throttling_threshold = fields.Integer(string="Throttling threshold (msg/sec)")

    active = fields.Boolean(default=True, index=True)

    @api.depends("queue_ids")
    def _compute_queue_count(self):
        mapped_data = read_counts_for_o2m(
            records=self, field_name="queue_ids", sudo=True
        )
        for rec in self:
            rec.queue_count = mapped_data.get(rec.id, 0)

    @api.depends("exchange_ids")
    def _compute_exchange_count(self):
        mapped_data = read_counts_for_o2m(
            records=self, field_name="exchange_ids", sudo=True
        )
        for rec in self:
            rec.exchange_count = mapped_data.get(rec.id, 0)

    @api.depends("event_ids")
    def _compute_event_count(self):
        mapped_data = read_counts_for_o2m(
            records=self, field_name="event_ids", sudo=True
        )
        for rec in self:
            rec.event_count = mapped_data.get(rec.id, 0)

    @api.depends("outgoing_route_ids")
    def _compute_outgoing_route_count(self):
        mapped_data = read_counts_for_o2m(
            records=self, field_name="outgoing_route_ids", sudo=True
        )
        for rec in self:
            rec.outgoing_route_count = mapped_data.get(rec.id, 0)

    @api.depends("outgoing_event_ids")
    def _compute_outgoing_event_count(self):
        mapped_data = read_counts_for_o2m(
            records=self, field_name="outgoing_event_ids", sudo=True
        )
        for rec in self:
            rec.outgoing_event_count = mapped_data.get(rec.id, 0)

    @api.private
    def get_connection_url(self):
        self.ensure_one()

        return (
            f"amqp://{self.user}:{self.password}@{self.host}:{self.port}/"
            f"{urllib.parse.quote_plus(self.virtual_host)}"
        )

    def _get_declare_config(self):
        return {
            "exchanges": [
                e._get_exchange_config()
                for e in self.exchange_ids
                if e.exchange_declare
            ],
            "queues": [q.get_queue_config() for q in self.queue_ids if q.queue_declare],
            "queue_bindings": [
                {
                    "queue_name": qb.queue_id.queue_name,
                    "exchange_name": qb.exchange_name,
                    "routing_key": qb.routing_key,
                }
                for qb in self.mapped("queue_ids.queue_binding_ids")
            ],
        }

    def _get_connection_config(self):
        return {
            "connection_id": self.id,
            "connection_url": self.get_connection_url(),
            "declare": self._get_declare_config(),
        }

    @api.private
    def get_consumer_config(self):
        """Return consumer config for background worker"""
        self.ensure_one()
        return dict(
            self._get_connection_config(),
            listen_queues=[q.get_queue_config() for q in self.queue_ids if q.listen],
        )

    @api.private
    def get_publisher_config(self):
        self.ensure_one()
        return dict(
            self._get_connection_config(),
            throttling_threshold=self.throttling_threshold,
        )

    @api.private
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

    def action_view_outgoing_events(self):
        self.ensure_one()
        return self.env["generic.mixin.get.action"].get_action_by_xmlid(
            "dark_rabbit.action_dark_rabbit_outgoing_event_list",
            domain=[("connection_id", "=", self.id)],
            context={"default_connection_id": self.id},
        )

    def action_view_outgoing_routes(self):
        self.ensure_one()
        return self.env["generic.mixin.get.action"].get_action_by_xmlid(
            "dark_rabbit.action_dark_rabbit_outgoing_routing_list",
            domain=[("connection_id", "=", self.id)],
            context={"default_connection_id": self.id},
        )

    def action_view_exchanges(self):
        self.ensure_one()
        return self.env["generic.mixin.get.action"].get_action_by_xmlid(
            "dark_rabbit.action_dark_rabbit_exchange_list",
            domain=[("connection_id", "=", self.id)],
            context={"default_connection_id": self.id},
        )

    def action_open_apply_schema_wizard(self):
        self.ensure_one()
        return self.env["generic.mixin.get.action"].get_action_by_xmlid(
            "dark_rabbit.action_dark_rabbit_apply_schema_wizard",
            context={"default_connection_id": self.id},
        )
