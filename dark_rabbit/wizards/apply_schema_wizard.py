import logging

from odoo import _, fields, models
from odoo.exceptions import UserError

from ..tools.rabbit_schema_spec import (
    RabbitSchemaSpec,
    SchemaConflictError,
    merge,
    parse_yaml,
)

_logger = logging.getLogger(__name__)


class ApplySchemaWizard(models.TransientModel):
    _name = "dark.rabbit.apply.schema.wizard"
    _description = "Dark Rabbit: Apply Schema to Connection"

    connection_id = fields.Many2one(
        comodel_name="dark.rabbit.connection",
        required=True,
        string="Connection",
    )
    schema_ids = fields.Many2many(
        comodel_name="dark.rabbit.schema",
        string="Schemas",
    )

    def action_apply(self):
        self.ensure_one()

        if not self.schema_ids:
            raise UserError(_("Select at least one schema to apply."))

        specs = []
        for schema in self.schema_ids:
            try:
                specs.append(parse_yaml(schema.spec or ""))
            except ValueError as exc:
                raise UserError(
                    _("Schema %(name)s: %(error)s", name=schema.name, error=exc)
                ) from exc

        try:
            merged = merge(specs)
        except SchemaConflictError as exc:
            raise UserError(str(exc)) from exc

        self._reconcile(self.connection_id, merged)

        return {"type": "ir.actions.act_window_close"}

    def _reconcile(self, connection, spec: RabbitSchemaSpec):
        """Reconcile merged spec against existing DB records on the connection.

        Creates missing entities and updates drifted fields.  Bindings and
        outgoing routings are additive — existing ones are never removed.

        Exchanges are processed before queues so DLX references can be
        resolved within the same apply.
        """
        Exchange = self.env["dark.rabbit.exchange"]
        Queue = self.env["dark.rabbit.queue"]
        Binding = self.env["dark.rabbit.queue.binding"]

        # --- exchanges ---
        for ex_spec in spec.exchanges.values():
            exchange = Exchange.search(
                [
                    ("connection_id", "=", connection.id),
                    ("name", "=", ex_spec.name),
                ],
                limit=1,
            )
            vals = {
                "exchange_declare": ex_spec.declare,
                "exchange_type": ex_spec.type,
                "exchange_durable": ex_spec.durable,
            }
            if not exchange:
                Exchange.create(
                    dict(vals, connection_id=connection.id, name=ex_spec.name)
                )
            else:
                exchange.write(vals)

        # --- queues ---
        for q_spec in spec.queues.values():
            queue = Queue.search(
                [
                    ("connection_id", "=", connection.id),
                    ("queue_name", "=", q_spec.name),
                ],
                limit=1,
            )
            vals = {
                "queue_declare": q_spec.declare,
                "queue_declare_durable": q_spec.durable,
                "queue_declare_exclusive": q_spec.exclusive,
                "queue_declare_auto_delete": q_spec.auto_delete,
                "listen": q_spec.listen,
                "listen_exclusive": q_spec.listen_exclusive,
            }
            if q_spec.dlx:
                dlx = Exchange.search(
                    [
                        ("connection_id", "=", connection.id),
                        ("name", "=", q_spec.dlx),
                    ],
                    limit=1,
                )
                if not dlx:
                    raise UserError(
                        _(
                            "Queue %(queue)s references DLX exchange %(dlx)s "
                            "which does not exist on this connection. "
                            "Add it to a schema and apply.",
                            queue=q_spec.name,
                            dlx=q_spec.dlx,
                        )
                    )
                vals["queue_declare_dlx_id"] = dlx.id
            if q_spec.dlq_routing:
                vals["queue_declare_dlq_routing"] = q_spec.dlq_routing
            if q_spec.handler:
                handler = self.env["dark.rabbit.handler"].search(
                    [("handler_code", "=", q_spec.handler)], limit=1
                )
                if not handler:
                    raise UserError(
                        _(
                            "Queue %(queue)s: handler %(handler)s not found. "
                            "Make sure the module that registers it is installed.",
                            queue=q_spec.name,
                            handler=q_spec.handler,
                        )
                    )
                vals["handler_id"] = handler.id

            if not queue:
                queue = Queue.create(
                    dict(
                        vals,
                        connection_id=connection.id,
                        queue_name=q_spec.name,
                    )
                )
            else:
                queue.write(vals)

            # --- bindings ---
            for b_spec in q_spec.bindings:
                exchange = Exchange.search(
                    [
                        ("connection_id", "=", connection.id),
                        ("name", "=", b_spec.exchange),
                    ],
                    limit=1,
                )
                if not exchange:
                    raise UserError(
                        _(
                            "Queue %(queue)s binding references exchange "
                            "%(exchange)s which does not exist on this "
                            "connection. Add it to a schema and apply.",
                            queue=q_spec.name,
                            exchange=b_spec.exchange,
                        )
                    )
                exists = Binding.search(
                    [
                        ("queue_id", "=", queue.id),
                        ("exchange_id", "=", exchange.id),
                        ("routing_key", "=", b_spec.routing_key),
                    ],
                    limit=1,
                )
                if not exists:
                    Binding.create(
                        {
                            "queue_id": queue.id,
                            "exchange_id": exchange.id,
                            "routing_key": b_spec.routing_key,
                            "bind": b_spec.bind,
                        }
                    )
                elif exists.bind != b_spec.bind:
                    exists.write({"bind": b_spec.bind})

        # --- outgoing routings ---
        self._reconcile_outgoing_routings(connection, spec)

    def _reconcile_outgoing_routings(self, connection, spec: RabbitSchemaSpec):
        OutgoingRouting = self.env["dark.rabbit.outgoing.routing"]
        EventType = self.env["dark.rabbit.outgoing.event.type"]
        Exchange = self.env["dark.rabbit.exchange"]
        Tag = self.env["dark.rabbit.outgoing.routing.tag"]

        for r_spec in spec.outgoing_routings:
            event_type = EventType.search([("code", "=", r_spec.event_type)], limit=1)
            if not event_type:
                raise UserError(
                    _(
                        "Outgoing routing: event type %(code)s not found. "
                        "Make sure the module that defines it is installed.",
                        code=r_spec.event_type,
                    )
                )

            exchange = Exchange.search(
                [
                    ("connection_id", "=", connection.id),
                    ("name", "=", r_spec.exchange),
                ],
                limit=1,
            )
            if not exchange:
                raise UserError(
                    _(
                        "Outgoing routing for %(event_type)s: exchange "
                        "%(exchange)s does not exist on this connection. "
                        "Add it to a schema and apply.",
                        event_type=r_spec.event_type,
                        exchange=r_spec.exchange,
                    )
                )

            require_tag_id = False
            if r_spec.require_tag:
                tag = Tag.search([("code", "=", r_spec.require_tag)], limit=1)
                if not tag:
                    raise UserError(
                        _(
                            "Outgoing routing for %(event_type)s: "
                            "tag %(tag)s not found.",
                            event_type=r_spec.event_type,
                            tag=r_spec.require_tag,
                        )
                    )
                require_tag_id = tag.id

            exists = OutgoingRouting.search(
                [
                    ("outgoing_event_type_id", "=", event_type.id),
                    ("connection_id", "=", connection.id),
                    ("exchange_id", "=", exchange.id),
                    ("routing_key", "=", r_spec.routing_key),
                    ("require_tag_id", "=", require_tag_id),
                ],
                limit=1,
            )
            if not exists:
                OutgoingRouting.create(
                    {
                        "outgoing_event_type_id": event_type.id,
                        "connection_id": connection.id,
                        "exchange_id": exchange.id,
                        "routing_key": r_spec.routing_key,
                        "require_tag_id": require_tag_id,
                    }
                )
