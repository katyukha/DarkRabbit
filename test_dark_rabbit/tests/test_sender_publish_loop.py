import datetime
from unittest import mock

from odoo.tests.common import TransactionCase

from odoo.addons.dark_rabbit.services import sender_worker
from odoo.addons.dark_rabbit.services.sender_worker import DarkRabbitSenderWorker

BASE = datetime.datetime(2026, 1, 1, 0, 0, 0)


class FakeChannel:
    # is_closed must stay mutable: a test flips it part way through a batch.
    __slots__ = ("is_closed",)

    def __init__(self, is_closed=False):
        self.is_closed = is_closed


class FakePublisher:
    """Stands in for DarkRabbitPublisher: only the flags the loop reads."""

    def __init__(self, can_send=True, scheduled_reload=False, is_closed=False):
        self.can_send = can_send
        self.scheduled_reload = scheduled_reload
        self.channel = FakeChannel(is_closed)

    def schedule_reload(self):
        self.scheduled_reload = True


class FakeRegistry:
    def __init__(self, publishers):
        self._publishers = publishers

    @property
    def active_connection_ids(self):
        return list(self._publishers)

    def get(self, connection_id):
        return self._publishers.get(connection_id)


class TestPublishLoop(TransactionCase):
    """`_publish_events`: which events each ready connection sends, and which
    connections are skipped before anything is queried."""

    def setUp(self):
        super().setUp()
        self.Event = self.env["dark.rabbit.outgoing.event"]
        self.conn_a = self._connection("conn-a")
        self.conn_b = self._connection("conn-b")

        self.published = []
        # _publish_events only touches these two attributes of the worker, so
        # it is built without running the background-service __init__.
        self.worker = object.__new__(DarkRabbitSenderWorker)
        self.worker._publish_event = self._record_publish

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

        created_at has a default, so it is written afterwards to control the
        ordering the sender relies on.
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

    def _record_publish(self, publisher, event):
        self.published.append(event)
        return True

    def _run(self, publishers):
        self.worker._publisher_registry = FakeRegistry(publishers)
        return self.worker._publish_events(self.env)

    # -------------------------------------------------- which events are sent

    def test_ready_publisher_sends_its_events_oldest_first(self):
        third = self._event(self.conn_a, 3)
        first = self._event(self.conn_a, 1)
        second = self._event(self.conn_a, 2)

        result = self._run({self.conn_a.id: FakePublisher()})

        self.assertEqual(self.published, [first, second, third])
        self.assertEqual((result.total, result.sent, result.failed), (3, 3, 0))

    def test_already_sent_events_are_not_resent(self):
        pending = self._event(self.conn_a, 1)
        self._event(self.conn_a, 2, sent=True)

        self._run({self.conn_a.id: FakePublisher()})

        self.assertEqual(self.published, [pending])

    def test_timestamp_breaks_created_at_ties(self):
        later = self._event(self.conn_a, 1, timestamp=20)
        earlier = self._event(self.conn_a, 1, timestamp=10)

        self._run({self.conn_a.id: FakePublisher()})

        self.assertEqual(self.published, [earlier, later])

    def test_only_the_connections_own_events_are_sent(self):
        a_event = self._event(self.conn_a, 1)
        self._event(self.conn_b, 2)

        self._run({self.conn_a.id: FakePublisher()})

        self.assertEqual(self.published, [a_event])

    def test_batch_is_limited_per_connection(self):
        for offset in range(6):
            self._event(self.conn_a, offset)
            self._event(self.conn_b, offset)

        with mock.patch.object(sender_worker, "BATCH_PUBLISH", 2):
            result = self._run(
                {self.conn_a.id: FakePublisher(), self.conn_b.id: FakePublisher()}
            )

        self.assertEqual(result.total, 4, "two per connection, not two overall")

    # ------------------------------------------------ which connections run

    def test_unusable_publisher_is_not_even_queried(self):
        """The point of the loop shape: a stalled publisher used to cost a
        query and a batch slot on every single cycle."""
        self._event(self.conn_a, 1)

        with mock.patch.object(self.Event.__class__, "search", autospec=True) as search:
            result = self._run({self.conn_a.id: FakePublisher(can_send=False)})

        search.assert_not_called()
        self.assertEqual(self.published, [])
        self.assertEqual(result.total, 0)

    def test_publisher_scheduled_for_reload_is_skipped(self):
        self._event(self.conn_a, 1)

        result = self._run({self.conn_a.id: FakePublisher(scheduled_reload=True)})

        self.assertEqual(self.published, [])
        self.assertEqual(result.total, 0)

    def test_closed_channel_schedules_reload_and_skips(self):
        self._event(self.conn_a, 1)
        publisher = FakePublisher(is_closed=True)

        result = self._run({self.conn_a.id: publisher})

        self.assertTrue(publisher.scheduled_reload)
        self.assertEqual(self.published, [])
        self.assertEqual(result.total, 0)

    def test_missing_publisher_is_skipped(self):
        self._event(self.conn_a, 1)

        result = self._run({self.conn_a.id: None})

        self.assertEqual(self.published, [])
        self.assertEqual(result.total, 0)

    def test_one_stalled_connection_does_not_block_another(self):
        """Fairness comes from the loop, not from how a batch is divided."""
        self._event(self.conn_a, 1)
        b_event = self._event(self.conn_b, 2)

        result = self._run(
            {
                self.conn_a.id: FakePublisher(can_send=False),
                self.conn_b.id: FakePublisher(),
            }
        )

        self.assertEqual(self.published, [b_event])
        self.assertEqual(result.total, 1)

    def test_no_ready_publishers_reports_nothing_to_do(self):
        """run_service breaks out and sleeps on total == 0. Previously the
        events were selected and skipped, so total stayed non-zero and the
        loop spun on work it could never do."""
        self._event(self.conn_a, 1)

        result = self._run({self.conn_a.id: FakePublisher(can_send=False)})

        self.assertEqual(result.total, 0)

    # ----------------------------------------------------- mid-batch failure

    def test_channel_closing_mid_batch_stops_and_counts_the_remainder(self):
        """Rather than failing every remaining event against a dead channel,
        stop and let the next cycle retry them."""
        for offset in range(3):
            self._event(self.conn_a, offset)
        publisher = FakePublisher()

        def close_after_first(pub, event):
            self.published.append(event)
            pub.channel.is_closed = True
            return True

        self.worker._publish_event = close_after_first
        result = self._run({self.conn_a.id: publisher})

        self.assertEqual(len(self.published), 1, "stopped after the channel closed")
        self.assertEqual((result.total, result.sent, result.skipped), (3, 1, 2))
        self.assertTrue(publisher.scheduled_reload)
