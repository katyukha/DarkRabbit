"""Tests for the Dark Rabbit schema feature.

Covers:
  - YAML parsing (valid, invalid, empty)
  - merge() happy-path and conflict detection
  - Wizard reconcile: create missing, update drifted, skip existing
  - Wizard end-to-end with multiple schemas
"""
from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase

from odoo.addons.dark_rabbit.tools.rabbit_schema_spec import (
    SchemaConflictError,
    merge,
    parse_yaml,
)

# ---------------------------------------------------------------------------
# Pure-Python parser tests (no DB)
# ---------------------------------------------------------------------------


class TestParseYaml(TransactionCase):
    def test_empty_spec_returns_empty(self):
        spec = parse_yaml("")
        self.assertEqual(spec.exchanges, {})
        self.assertEqual(spec.queues, {})

    def test_none_like_whitespace_returns_empty(self):
        spec = parse_yaml("   \n  ")
        self.assertEqual(spec.exchanges, {})
        self.assertEqual(spec.queues, {})

    def test_valid_exchange(self):
        spec = parse_yaml(
            """
exchanges:
  - name: my.events
    type: topic
    durable: true
"""
        )
        self.assertIn("my.events", spec.exchanges)
        ex = spec.exchanges["my.events"]
        self.assertEqual(ex.type, "topic")
        self.assertTrue(ex.durable)
        self.assertTrue(ex.declare)

    def test_exchange_defaults(self):
        spec = parse_yaml(
            """
exchanges:
  - name: bare.exchange
"""
        )
        ex = spec.exchanges["bare.exchange"]
        self.assertEqual(ex.type, "topic")
        self.assertTrue(ex.durable)
        self.assertTrue(ex.declare)

    def test_invalid_exchange_type_raises(self):
        with self.assertRaises(ValueError):
            parse_yaml(
                """
exchanges:
  - name: bad
    type: invalid_type
"""
            )

    def test_exchange_missing_name_raises(self):
        with self.assertRaises(ValueError):
            parse_yaml(
                """
exchanges:
  - type: topic
"""
            )

    def test_valid_queue_with_binding(self):
        spec = parse_yaml(
            """
exchanges:
  - name: evt
queues:
  - name: my.tasks
    durable: true
    bindings:
      - exchange: evt
        routing_key: "my.tasks.*"
"""
        )
        self.assertIn("my.tasks", spec.queues)
        q = spec.queues["my.tasks"]
        self.assertTrue(q.durable)
        self.assertEqual(len(q.bindings), 1)
        self.assertEqual(q.bindings[0].exchange, "evt")
        self.assertEqual(q.bindings[0].routing_key, "my.tasks.*")

    def test_queue_defaults(self):
        spec = parse_yaml(
            """
queues:
  - name: bare.queue
"""
        )
        q = spec.queues["bare.queue"]
        self.assertTrue(q.declare)
        self.assertTrue(q.durable)
        self.assertFalse(q.exclusive)
        self.assertFalse(q.auto_delete)
        self.assertIsNone(q.dlx)
        self.assertIsNone(q.dlq_routing)

    def test_binding_missing_exchange_raises(self):
        with self.assertRaises(ValueError):
            parse_yaml(
                """
queues:
  - name: q
    bindings:
      - routing_key: foo
"""
            )

    def test_duplicate_exchange_in_same_spec_raises(self):
        with self.assertRaises(ValueError):
            parse_yaml(
                """
exchanges:
  - name: dup
  - name: dup
"""
            )

    def test_queue_with_dlx(self):
        spec = parse_yaml(
            """
queues:
  - name: my.queue
    dlx: dead.letters
    dlq_routing: my.queue.dead
"""
        )
        q = spec.queues["my.queue"]
        self.assertEqual(q.dlx, "dead.letters")
        self.assertEqual(q.dlq_routing, "my.queue.dead")

    def test_invalid_yaml_raises(self):
        with self.assertRaises(ValueError):
            parse_yaml("key: [unclosed")


# ---------------------------------------------------------------------------
# Merge tests
# ---------------------------------------------------------------------------


class TestMerge(TransactionCase):
    def test_merge_disjoint_schemas(self):
        spec_a = parse_yaml(
            """
exchanges:
  - name: ex.a
"""
        )
        spec_b = parse_yaml(
            """
exchanges:
  - name: ex.b
"""
        )
        merged = merge([spec_a, spec_b])
        self.assertIn("ex.a", merged.exchanges)
        self.assertIn("ex.b", merged.exchanges)

    def test_merge_same_exchange_identical_config_ok(self):
        yaml = """
exchanges:
  - name: shared.ex
    type: topic
    durable: true
"""
        merged = merge([parse_yaml(yaml), parse_yaml(yaml)])
        self.assertIn("shared.ex", merged.exchanges)

    def test_merge_exchange_type_conflict_raises(self):
        a = parse_yaml("exchanges:\n  - name: ex\n    type: topic\n")
        b = parse_yaml("exchanges:\n  - name: ex\n    type: direct\n")
        with self.assertRaises(SchemaConflictError) as ctx:
            merge([a, b])
        self.assertIn("ex", str(ctx.exception))
        self.assertIn("type", str(ctx.exception))

    def test_merge_exchange_durable_conflict_raises(self):
        a = parse_yaml("exchanges:\n  - name: ex\n    durable: true\n")
        b = parse_yaml("exchanges:\n  - name: ex\n    durable: false\n")
        with self.assertRaises(SchemaConflictError):
            merge([a, b])

    def test_merge_queue_durable_conflict_raises(self):
        a = parse_yaml("queues:\n  - name: q\n    durable: true\n")
        b = parse_yaml("queues:\n  - name: q\n    durable: false\n")
        with self.assertRaises(SchemaConflictError):
            merge([a, b])

    def test_merge_collects_all_conflicts(self):
        a = parse_yaml(
            """
exchanges:
  - name: ex1
    type: topic
  - name: ex2
    type: topic
"""
        )
        b = parse_yaml(
            """
exchanges:
  - name: ex1
    type: direct
  - name: ex2
    type: fanout
"""
        )
        with self.assertRaises(SchemaConflictError) as ctx:
            merge([a, b])
        msg = str(ctx.exception)
        self.assertIn("ex1", msg)
        self.assertIn("ex2", msg)

    def test_merge_declare_or_semantics(self):
        a = parse_yaml("exchanges:\n  - name: ex\n    declare: false\n")
        b = parse_yaml("exchanges:\n  - name: ex\n    declare: true\n")
        merged = merge([a, b])
        self.assertTrue(merged.exchanges["ex"].declare)

    def test_merge_bindings_unioned(self):
        a = parse_yaml(
            """
queues:
  - name: q
    bindings:
      - exchange: ex
        routing_key: "a.*"
"""
        )
        b = parse_yaml(
            """
queues:
  - name: q
    bindings:
      - exchange: ex
        routing_key: "b.*"
"""
        )
        merged = merge([a, b])
        keys = {bind.routing_key for bind in merged.queues["q"].bindings}
        self.assertEqual(keys, {"a.*", "b.*"})

    def test_merge_duplicate_binding_deduplicated(self):
        yaml = """
queues:
  - name: q
    bindings:
      - exchange: ex
        routing_key: "same.*"
"""
        merged = merge([parse_yaml(yaml), parse_yaml(yaml)])
        self.assertEqual(len(merged.queues["q"].bindings), 1)

    def test_merge_empty_list_returns_empty(self):
        merged = merge([])
        self.assertEqual(merged.exchanges, {})
        self.assertEqual(merged.queues, {})


# ---------------------------------------------------------------------------
# Helpers for Odoo-layer tests
# ---------------------------------------------------------------------------


def _make_connection(env):
    return env["dark.rabbit.connection"].create(
        {
            "name": "Schema Test Conn",
            "code": "schema-test-conn",
            "host": "localhost",
            "port": 5672,
        }
    )


def _make_schema(env, name, spec):
    return env["dark.rabbit.schema"].create({"name": name, "spec": spec})


# ---------------------------------------------------------------------------
# Schema model validation
# ---------------------------------------------------------------------------


class TestSchemaModel(TransactionCase):
    def test_invalid_spec_raises_validation_error(self):
        with self.assertRaises(ValidationError):
            _make_schema(self.env, "bad", "exchanges:\n  - type: topic\n")

    def test_empty_spec_is_valid(self):
        schema = _make_schema(self.env, "empty", "")
        self.assertTrue(schema.id)

    def test_duplicate_name_raises(self):
        _make_schema(self.env, "dup.schema", "")
        with self.assertRaises(ValidationError):
            _make_schema(self.env, "dup.schema", "")


# ---------------------------------------------------------------------------
# Wizard reconcile tests
# ---------------------------------------------------------------------------


class TestApplySchemaWizard(TransactionCase):
    def setUp(self):
        super().setUp()
        self.conn = _make_connection(self.env)

    def _apply(self, schemas):
        wizard = self.env["dark.rabbit.apply.schema.wizard"].create(
            {
                "connection_id": self.conn.id,
                "schema_ids": [(6, 0, [s.id for s in schemas])],
            }
        )
        wizard.action_apply()

    def test_apply_creates_exchange(self):
        schema = _make_schema(
            self.env,
            "test.exchange.create",
            "exchanges:\n  - name: new.exchange\n    type: direct\n",
        )
        self._apply([schema])

        ex = self.env["dark.rabbit.exchange"].search(
            [("connection_id", "=", self.conn.id), ("name", "=", "new.exchange")]
        )
        self.assertEqual(len(ex), 1)
        self.assertEqual(ex.exchange_type, "direct")
        self.assertTrue(ex.exchange_declare)

    def test_apply_updates_drifted_exchange(self):
        self.env["dark.rabbit.exchange"].create(
            {
                "connection_id": self.conn.id,
                "name": "drifted.ex",
                "exchange_type": "direct",
                "exchange_durable": False,
                "exchange_declare": True,
            }
        )
        schema = _make_schema(
            self.env,
            "test.drift.exchange",
            "exchanges:\n  - name: drifted.ex\n    type: topic\n    durable: true\n",
        )
        self._apply([schema])

        ex = self.env["dark.rabbit.exchange"].search(
            [("connection_id", "=", self.conn.id), ("name", "=", "drifted.ex")]
        )
        self.assertEqual(ex.exchange_type, "topic")
        self.assertTrue(ex.exchange_durable)

    def test_apply_does_not_duplicate_existing_exchange(self):
        self.env["dark.rabbit.exchange"].create(
            {
                "connection_id": self.conn.id,
                "name": "existing.ex",
                "exchange_type": "topic",
                "exchange_durable": True,
                "exchange_declare": True,
            }
        )
        schema = _make_schema(
            self.env,
            "test.no.dup.exchange",
            "exchanges:\n  - name: existing.ex\n    type: topic\n    durable: true\n",
        )
        self._apply([schema])

        count = self.env["dark.rabbit.exchange"].search_count(
            [("connection_id", "=", self.conn.id), ("name", "=", "existing.ex")]
        )
        self.assertEqual(count, 1)

    def test_apply_creates_queue(self):
        schema = _make_schema(
            self.env,
            "test.queue.create",
            "queues:\n  - name: new.queue\n    durable: true\n",
        )
        self._apply([schema])

        q = self.env["dark.rabbit.queue"].search(
            [
                ("connection_id", "=", self.conn.id),
                ("queue_name", "=", "new.queue"),
            ]
        )
        self.assertEqual(len(q), 1)
        self.assertTrue(q.queue_declare_durable)

    def test_apply_creates_binding(self):
        schema = _make_schema(
            self.env,
            "test.binding.create",
            """
exchanges:
  - name: bind.ex
queues:
  - name: bind.q
    bindings:
      - exchange: bind.ex
        routing_key: "bind.*"
""",
        )
        self._apply([schema])

        ex = self.env["dark.rabbit.exchange"].search(
            [("connection_id", "=", self.conn.id), ("name", "=", "bind.ex")]
        )
        q = self.env["dark.rabbit.queue"].search(
            [("connection_id", "=", self.conn.id), ("queue_name", "=", "bind.q")]
        )
        binding = self.env["dark.rabbit.queue.binding"].search(
            [
                ("queue_id", "=", q.id),
                ("exchange_id", "=", ex.id),
                ("routing_key", "=", "bind.*"),
            ]
        )
        self.assertEqual(len(binding), 1)

    def test_apply_does_not_duplicate_existing_binding(self):
        schema = _make_schema(
            self.env,
            "test.binding.no.dup",
            """
exchanges:
  - name: dup.bind.ex
queues:
  - name: dup.bind.q
    bindings:
      - exchange: dup.bind.ex
        routing_key: "dup.*"
""",
        )
        self._apply([schema])
        self._apply([schema])

        ex = self.env["dark.rabbit.exchange"].search(
            [("connection_id", "=", self.conn.id), ("name", "=", "dup.bind.ex")]
        )
        q = self.env["dark.rabbit.queue"].search(
            [
                ("connection_id", "=", self.conn.id),
                ("queue_name", "=", "dup.bind.q"),
            ]
        )
        count = self.env["dark.rabbit.queue.binding"].search_count(
            [
                ("queue_id", "=", q.id),
                ("exchange_id", "=", ex.id),
                ("routing_key", "=", "dup.*"),
            ]
        )
        self.assertEqual(count, 1)

    def test_conflicting_schemas_raise_user_error(self):
        schema_a = _make_schema(
            self.env,
            "test.conflict.a",
            "exchanges:\n  - name: conflict.ex\n    type: topic\n",
        )
        schema_b = _make_schema(
            self.env,
            "test.conflict.b",
            "exchanges:\n  - name: conflict.ex\n    type: direct\n",
        )
        with self.assertRaises(UserError) as ctx:
            self._apply([schema_a, schema_b])
        self.assertIn("conflict.ex", str(ctx.exception))

    def test_no_schemas_selected_raises_user_error(self):
        wizard = self.env["dark.rabbit.apply.schema.wizard"].create(
            {"connection_id": self.conn.id}
        )
        with self.assertRaises(UserError):
            wizard.action_apply()

    def test_two_schemas_merged_and_applied(self):
        schema_a = _make_schema(
            self.env,
            "test.multi.a",
            "exchanges:\n  - name: multi.ex\nqueues:\n  - name: queue.a\n",
        )
        schema_b = _make_schema(
            self.env,
            "test.multi.b",
            "queues:\n  - name: queue.b\n",
        )
        self._apply([schema_a, schema_b])

        self.assertTrue(
            self.env["dark.rabbit.exchange"].search_count(
                [("connection_id", "=", self.conn.id), ("name", "=", "multi.ex")]
            )
        )
        self.assertTrue(
            self.env["dark.rabbit.queue"].search_count(
                [
                    ("connection_id", "=", self.conn.id),
                    ("queue_name", "=", "queue.a"),
                ]
            )
        )
        self.assertTrue(
            self.env["dark.rabbit.queue"].search_count(
                [
                    ("connection_id", "=", self.conn.id),
                    ("queue_name", "=", "queue.b"),
                ]
            )
        )

    def test_binding_references_missing_exchange_raises(self):
        schema = _make_schema(
            self.env,
            "test.missing.exchange",
            "queues:\n  - name: orphan.q\n    bindings:\n"
            "      - exchange: no.such.ex\n        routing_key: foo\n",
        )
        with self.assertRaises(UserError):
            self._apply([schema])
