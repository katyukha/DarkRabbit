"""Pure-Python representation of a RabbitMQ schema spec.

A schema spec declares the AMQP entities (exchanges, queues, bindings) that
an application requires.  It is intentionally free of Odoo dependencies so
that it can be unit-tested without a running Odoo instance.

Public API
----------
parse_yaml(text)        Parse a YAML string into a RabbitSchemaSpec.
merge(specs)            Merge a list of specs; raise SchemaConflictError on
                        incompatible declarations for the same entity name.
SchemaConflictError     Raised by merge() when two specs disagree.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import yaml

_logger = logging.getLogger(__name__)

VALID_EXCHANGE_TYPES = frozenset({"topic", "direct", "fanout", "headers"})


class SchemaConflictError(ValueError):
    """Raised when two schema specs declare the same entity with
    incompatible configuration."""


# ---------------------------------------------------------------------------
# Spec dataclasses
# ---------------------------------------------------------------------------


@dataclass
class BindingSpec:
    exchange: str
    routing_key: str = ""


@dataclass
class ExchangeSpec:
    name: str
    declare: bool = True
    type: str = "topic"
    durable: bool = True


@dataclass
class QueueSpec:
    name: str
    declare: bool = True
    durable: bool = True
    exclusive: bool = False
    auto_delete: bool = False
    dlx: str | None = None
    dlq_routing: str | None = None
    bindings: list[BindingSpec] = field(default_factory=list)


@dataclass
class RabbitSchemaSpec:
    exchanges: dict[str, ExchangeSpec] = field(default_factory=dict)
    queues: dict[str, QueueSpec] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _parse_exchange(raw: dict) -> ExchangeSpec:
    name = raw.get("name", "").strip()
    if not name:
        raise ValueError("Exchange entry is missing required field 'name'")
    exchange_type = raw.get("type", "topic")
    if exchange_type not in VALID_EXCHANGE_TYPES:
        raise ValueError(
            f"Exchange {name!r}: invalid type {exchange_type!r}. "
            f"Valid types: {sorted(VALID_EXCHANGE_TYPES)}"
        )
    return ExchangeSpec(
        name=name,
        declare=bool(raw.get("declare", True)),
        type=exchange_type,
        durable=bool(raw.get("durable", True)),
    )


def _parse_queue(raw: dict) -> QueueSpec:
    name = raw.get("name", "").strip()
    if not name:
        raise ValueError("Queue entry is missing required field 'name'")
    bindings = []
    for b in raw.get("bindings", []):
        ex_name = b.get("exchange", "").strip()
        if not ex_name:
            raise ValueError(f"Queue {name!r}: binding entry is missing 'exchange'")
        bindings.append(
            BindingSpec(
                exchange=ex_name,
                routing_key=b.get("routing_key", ""),
            )
        )
    return QueueSpec(
        name=name,
        declare=bool(raw.get("declare", True)),
        durable=bool(raw.get("durable", True)),
        exclusive=bool(raw.get("exclusive", False)),
        auto_delete=bool(raw.get("auto_delete", False)),
        dlx=raw.get("dlx") or None,
        dlq_routing=raw.get("dlq_routing") or None,
        bindings=bindings,
    )


def parse_yaml(text: str) -> RabbitSchemaSpec:
    """Parse a YAML schema spec string into a RabbitSchemaSpec.

    Raises ValueError on structural or validation errors.
    """
    if not text or not text.strip():
        return RabbitSchemaSpec()

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML: {exc}") from exc

    if data is None:
        return RabbitSchemaSpec()

    if not isinstance(data, dict):
        raise ValueError("Schema spec must be a YAML mapping at the top level")

    exchanges: dict[str, ExchangeSpec] = {}
    for raw in data.get("exchanges") or []:
        ex = _parse_exchange(raw)
        if ex.name in exchanges:
            raise ValueError(f"Duplicate exchange {ex.name!r} within the same spec")
        exchanges[ex.name] = ex

    queues: dict[str, QueueSpec] = {}
    for raw in data.get("queues") or []:
        q = _parse_queue(raw)
        if q.name in queues:
            raise ValueError(f"Duplicate queue {q.name!r} within the same spec")
        queues[q.name] = q

    return RabbitSchemaSpec(exchanges=exchanges, queues=queues)


# ---------------------------------------------------------------------------
# Merging
# ---------------------------------------------------------------------------


def _merge_exchange(existing: ExchangeSpec, incoming: ExchangeSpec) -> ExchangeSpec:
    """Return merged exchange or raise SchemaConflictError."""
    conflicts = []
    if existing.type != incoming.type:
        conflicts.append(f"type: {existing.type!r} vs {incoming.type!r}")
    if existing.durable != incoming.durable:
        conflicts.append(f"durable: {existing.durable} vs {incoming.durable}")
    if conflicts:
        raise SchemaConflictError(
            f"Exchange {existing.name!r} conflict: {', '.join(conflicts)}"
        )
    return ExchangeSpec(
        name=existing.name,
        # OR semantics: declare=True from any schema wins
        declare=existing.declare or incoming.declare,
        type=existing.type,
        durable=existing.durable,
    )


def _merge_queue(existing: QueueSpec, incoming: QueueSpec) -> QueueSpec:
    """Return merged queue or raise SchemaConflictError."""
    conflicts = []
    if existing.durable != incoming.durable:
        conflicts.append(f"durable: {existing.durable} vs {incoming.durable}")
    if existing.exclusive != incoming.exclusive:
        conflicts.append(f"exclusive: {existing.exclusive} vs {incoming.exclusive}")
    if existing.auto_delete != incoming.auto_delete:
        conflicts.append(
            f"auto_delete: {existing.auto_delete} vs {incoming.auto_delete}"
        )
    if existing.dlx != incoming.dlx:
        conflicts.append(f"dlx: {existing.dlx!r} vs {incoming.dlx!r}")
    if existing.dlq_routing != incoming.dlq_routing:
        conflicts.append(
            f"dlq_routing: {existing.dlq_routing!r} vs {incoming.dlq_routing!r}"
        )
    if conflicts:
        raise SchemaConflictError(
            f"Queue {existing.name!r} conflict: {', '.join(conflicts)}"
        )
    # Union bindings by (exchange, routing_key)
    existing_keys = {(b.exchange, b.routing_key) for b in existing.bindings}
    extra = [
        b for b in incoming.bindings if (b.exchange, b.routing_key) not in existing_keys
    ]
    return QueueSpec(
        name=existing.name,
        declare=existing.declare or incoming.declare,
        durable=existing.durable,
        exclusive=existing.exclusive,
        auto_delete=existing.auto_delete,
        dlx=existing.dlx,
        dlq_routing=existing.dlq_routing,
        bindings=existing.bindings + extra,
    )


def merge(specs: list[RabbitSchemaSpec]) -> RabbitSchemaSpec:
    """Merge a list of RabbitSchemaSpec instances into one.

    All conflicts are collected before raising so the error message lists
    every problem at once.

    Raises SchemaConflictError if any two specs declare the same exchange or
    queue with incompatible configuration.
    """
    merged_exchanges: dict[str, ExchangeSpec] = {}
    merged_queues: dict[str, QueueSpec] = {}
    errors: list[str] = []

    for spec in specs:
        for name, ex in spec.exchanges.items():
            if name in merged_exchanges:
                try:
                    merged_exchanges[name] = _merge_exchange(merged_exchanges[name], ex)
                except SchemaConflictError as exc:
                    errors.append(str(exc))
            else:
                merged_exchanges[name] = ex

        for name, q in spec.queues.items():
            if name in merged_queues:
                try:
                    merged_queues[name] = _merge_queue(merged_queues[name], q)
                except SchemaConflictError as exc:
                    errors.append(str(exc))
            else:
                merged_queues[name] = q

    if errors:
        raise SchemaConflictError(
            "Schema merge failed due to conflicts:\n"
            + "\n".join(f"  - {e}" for e in errors)
        )

    return RabbitSchemaSpec(exchanges=merged_exchanges, queues=merged_queues)
