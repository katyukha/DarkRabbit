import datetime

from odoo.tests.common import TransactionCase

from odoo.addons.dark_rabbit.services.sender_worker import get_events_to_publish

BASE = datetime.datetime(2026, 1, 1, 0, 0, 0)


class TestSenderEventSelection(TransactionCase):
    """Which events the sender picks up for a set of active connections."""

    def setUp(self):
        super().setUp()
        self.Event = self.env["dark.rabbit.outgoing.event"]
        self.conn_a = self._connection("conn-a")
        self.conn_b = self._connection("conn-b")
        self.conn_c = self._connection("conn-c")

    def _connection(self, code):
        return self.env["dark.rabbit.connection"].create(
            {
                "name": code,
                "code": code,
                "host": "localhost",
                "port": 5672,
                "user": "dark.rabbit",
                "password": "dark.rabbit",
            }
        )

    def _event(self, connection, offset, sent=False, timestamp=0):
        """Create an outgoing event ``offset`` seconds after BASE.

        created_at has a default, so it is written explicitly afterwards to
        control the ordering the sender relies on.
        """
        event = self.Event.create(
            {
                "connection_id": connection.id,
                "body": "{}",
                "exchange": "test.exchange",
                "routing_key": "test",
                "timestamp": timestamp,
                "sent_at": BASE if sent else False,
            }
        )
        event.created_at = BASE + datetime.timedelta(seconds=offset)
        return event

    def _ids(self, connections):
        return [c.id for c in connections]

    def test_only_unsent_events_are_selected(self):
        pending = self._event(self.conn_a, 1)
        self._event(self.conn_a, 2, sent=True)

        events = get_events_to_publish(self.env, self._ids([self.conn_a]))

        self.assertEqual(events, pending)

    def test_only_listed_connections_are_selected(self):
        wanted = self._event(self.conn_a, 1)
        self._event(self.conn_b, 2)

        events = get_events_to_publish(self.env, self._ids([self.conn_a]))

        self.assertEqual(events, wanted)

    def test_no_active_connections_selects_nothing(self):
        self._event(self.conn_a, 1)

        events = get_events_to_publish(self.env, [])

        self.assertFalse(events)

    def test_oldest_first_within_a_connection(self):
        third = self._event(self.conn_a, 3)
        first = self._event(self.conn_a, 1)
        second = self._event(self.conn_a, 2)

        events = get_events_to_publish(self.env, self._ids([self.conn_a]))

        self.assertEqual(list(events), [first, second, third])

    def test_timestamp_breaks_created_at_ties(self):
        later = self._event(self.conn_a, 1, timestamp=20)
        earlier = self._event(self.conn_a, 1, timestamp=10)

        events = get_events_to_publish(self.env, self._ids([self.conn_a]))

        self.assertEqual(list(events), [earlier, later])

    def test_backlog_on_one_connection_does_not_starve_the_others(self):
        """The reason for querying per connection.

        conn_a holds the oldest events, so a single query ordered by created_at
        with a global limit returned only conn_a's -- conn_b and conn_c never
        got sent while that backlog lasted.
        """
        for offset in range(20):
            self._event(self.conn_a, offset)
        b_event = self._event(self.conn_b, 100)
        c_event = self._event(self.conn_c, 101)

        events = get_events_to_publish(
            self.env, self._ids([self.conn_a, self.conn_b, self.conn_c]), limit=6
        )

        self.assertIn(b_event, events, "backlogged conn_a must not starve conn_b")
        self.assertIn(c_event, events, "backlogged conn_a must not starve conn_c")

    def test_each_connection_gets_its_own_batch(self):
        """``limit`` is per connection, so a cycle carries up to
        limit * len(connection_ids) events."""
        for offset in range(20):
            self._event(self.conn_a, offset)
            self._event(self.conn_b, offset)
            self._event(self.conn_c, offset)

        events = get_events_to_publish(
            self.env, self._ids([self.conn_a, self.conn_b, self.conn_c]), limit=3
        )

        self.assertEqual(len(events), 9)
        for connection in (self.conn_a, self.conn_b, self.conn_c):
            self.assertEqual(
                len(events.filtered(lambda e, c=connection: e.connection_id == c)), 3
            )

    def test_single_connection_keeps_the_whole_batch(self):
        for offset in range(20):
            self._event(self.conn_a, offset)

        events = get_events_to_publish(self.env, self._ids([self.conn_a]), limit=10)

        self.assertEqual(len(events), 10)


class TestSenderIndex(TransactionCase):
    """The index the selection above depends on."""

    def test_sender_index_leads_with_connection_id(self):
        """Leading column decides everything here: with connection_id first the
        equality and the ORDER BY are both answered by the index. Anything else
        makes the sender walk other connections' backlogs."""
        self.env.cr.execute(
            "SELECT indexdef FROM pg_indexes WHERE indexname = %s",
            ("dark_rabbit_outgoing_event__sender_search_v2__idx",),
        )
        row = self.env.cr.fetchone()
        self.assertTrue(row, "sender index is missing")
        indexdef = row[0]
        self.assertIn(
            '("connection_id", "created_at", "timestamp", "id")'.replace('"', ""),
            indexdef.replace('"', ""),
            indexdef,
        )
        self.assertIn("sent_at IS NULL", indexdef, "index must stay partial")
