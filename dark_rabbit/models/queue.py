from odoo import models, fields, api

from odoo.addons.generic_mixin.tools.x2m_agg_utils import read_counts_for_o2m


class DarkRabbitQueue(models.Model):
    """ This model represents RabbitMQ queue
    """
    _name = 'dark.rabbit.queue'
    _description = 'Dark Rabbit: Queue'
    _order = 'connection_id, queue_name'
    _rec_name = 'queue_name'

    connection_id = fields.Many2one(
        comodel_name='dark.rabbit.connection',
        required=True,
        index=True,
    )
    queue_name = fields.Char(required=True, index=True)

    listen = fields.Boolean(
        index=True,
        help="If set, then this queue will be listened for new messages")
    listen_exclusive = fields.Boolean(
        help="Do not allow other consumers on the queue")

    queue_declare = fields.Boolean(string="Declare queue")
    queue_declare_durable = fields.Boolean(string="Queue durable")
    queue_declare_exclusive = fields.Boolean(string="Queue exclusive")
    queue_declare_auto_delete = fields.Boolean(
        string="Queue auto-delete",
        help="Automatically delete queue after consumer cancels or disconnects")

    queue_binding_ids = fields.One2many(
        comodel_name='dark.rabbit.queue.binding',
        inverse_name='queue_id',
        string="Bind queue to exchanges via specified routing keys")

    handler_id = fields.Many2one(comodel_name='dark.rabbit.handler')

    event_ids = fields.One2many(
        comodel_name='dark.rabbit.event',
        inverse_name='queue_id')
    event_count = fields.Integer(
        compute='_compute_event_count', readonly=True)

    active = fields.Boolean(default=True, index=True)

    @api.depends('event_ids')
    def _compute_event_count(self):
        mapped_data = read_counts_for_o2m(
            records=self, field_name="event_ids", sudo=True
        )
        for rec in self:
            rec.event_count = mapped_data.get(rec.id, 0)

    def get_queue_config(self):
        return {
            'queue_name': self.queue_name,
            'listen_exclusive': self.listen_exclusive,
            'queue_id': self.id,
            'handler_id': self.handler_id.id,
            'queue_declare': {
                'durable': self.queue_declare_durable,
                'exclusive': self.listen_exclusive,
                'auto_delete': self.queue_declare_auto_delete,
            } if self.queue_declare else False,
            'bindings': [
                {
                    'exchange_name': qb.exchange_name,
                    'routing_key': qb.routing_key,
                } for qb in self.queue_binding_ids
            ],
        }

    def action_view_events(self):
        self.ensure_one()
        return self.env["generic.mixin.get.action"].get_action_by_xmlid(
            "dark_rabbit.action_dark_rabbit_event_list",
            domain=[("queue_id", "=", self.id)],
        )
