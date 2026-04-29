import logging

from odoo import api, fields, models

from ..tools.rabbit_schema_spec import (
    BindingSpec,
    ExchangeSpec,
    QueueSpec,
    RabbitSchemaSpec,
    to_yaml,
)

_logger = logging.getLogger(__name__)


def _spec_from_connection(connection) -> RabbitSchemaSpec:
    exchanges = {}
    for ex in connection.exchange_ids:
        exchanges[ex.name] = ExchangeSpec(
            name=ex.name,
            declare=ex.exchange_declare,
            type=ex.exchange_type or "topic",
            durable=ex.exchange_durable,
        )

    queues = {}
    for q in connection.queue_ids:
        bindings = [
            BindingSpec(
                exchange=b.exchange_id.name,
                routing_key=b.routing_key or "",
            )
            for b in q.queue_binding_ids
            if b.exchange_id
        ]
        queues[q.queue_name] = QueueSpec(
            name=q.queue_name,
            declare=q.queue_declare,
            durable=q.queue_declare_durable,
            exclusive=q.queue_declare_exclusive,
            auto_delete=q.queue_declare_auto_delete,
            dlx=q.queue_declare_dlx or None,
            dlq_routing=q.queue_declare_dlq_routing or None,
            bindings=bindings,
        )

    return RabbitSchemaSpec(exchanges=exchanges, queues=queues)


class FillSchemaFromConnectionWizard(models.TransientModel):
    _name = "dark.rabbit.fill.schema.wizard"
    _description = "Dark Rabbit: Fill Schema from Connection"

    schema_id = fields.Many2one(
        comodel_name="dark.rabbit.schema",
        required=True,
        string="Schema",
    )
    connection_id = fields.Many2one(
        comodel_name="dark.rabbit.connection",
        string="Connection",
    )
    spec = fields.Text(
        string="Generated Spec",
        compute="_compute_spec",
        readonly=False,
        store=True,
    )

    @api.depends("connection_id")
    def _compute_spec(self):
        for rec in self:
            if not rec.connection_id:
                rec.spec = ""
                continue
            rec.spec = to_yaml(_spec_from_connection(rec.connection_id))

    def action_apply(self):
        self.ensure_one()
        self.schema_id.spec = self.spec
        return {"type": "ir.actions.act_window_close"}
