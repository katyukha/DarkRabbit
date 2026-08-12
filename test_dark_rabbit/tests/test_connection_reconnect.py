import pika.exceptions

from odoo.tests.common import TransactionCase
from odoo.tools import mute_logger

from odoo.addons.dark_rabbit.tools.dark_connection_base import DarkRabbitConnectionBase
from odoo.addons.dark_rabbit.tools.dark_connection_pool import DarkConnectionPool

CONN_ID = 1

#: The pool logs every detected failure at ERROR level, and Odoo's test
#: runner treats an ERROR record emitted during a test as a failure.
POOL_LOGGER = "odoo.addons.dark_rabbit.tools.dark_connection_pool"


class FakeChannel:
    # is_closed must stay mutable: a test flips it part way through a batch.
    __slots__ = ("is_closed",)

    def __init__(self, is_closed=False):
        self.is_closed = is_closed


class FakeConnection(DarkRabbitConnectionBase):
    """A connection with the broker removed and nothing else.

    Subclassing the real class on purpose: ``config``, ``schedule_reload`` and
    ``scheduled_reload`` are exactly the parts under test, so they must be the
    real implementations.
    """

    def __init__(self, config):
        super().__init__(config)
        self.close_count = 0
        self.raise_on_process = None
        self._connection = object()
        self._channel = FakeChannel()
        self._suspended = False

    def connect(self):  # never talk to a broker
        pass

    def close(self):
        self.close_count += 1

    def process_data_events(self, time_limit=None):
        if self.raise_on_process:
            raise self.raise_on_process


class TestConnectionReconnect(TransactionCase):
    """Detecting a broken connection and rebuilding it.

    This is the whole recovery path for both the sender and the consumer, and
    it works indirectly: ``schedule_reload`` does not reconnect anything, it
    adds a key to the connection's own config so that the next
    ``update_config`` comparison finds it different and rebuilds it.
    """

    def setUp(self):
        super().setUp()
        self.built = []
        self.pool = DarkConnectionPool(connection_factory=self._factory)

    def _factory(self, config):
        connection = FakeConnection(config)
        self.built.append(connection)
        return connection

    def _db_config(self):
        """Config as the workers read it: a fresh dict on every call.

        Freshness matters. ``schedule_reload`` mutates the connection's own
        config dict, and ``update_config`` compares that against this one -- if
        a caller handed back the *same* dict object, the mutation would land on
        both sides, the comparison would still be equal, and nothing would ever
        be rebuilt.
        """
        return {
            CONN_ID: {
                "connection_id": CONN_ID,
                "connection_url": "amqp://guest:guest@localhost:5672/",
            }
        }

    def _start(self):
        self.pool.update_config(self._db_config())
        return self.pool.get(CONN_ID)

    # ------------------------------------------------------------- detection

    def test_healthy_connection_is_not_scheduled_for_reload(self):
        connection = self._start()

        self.pool.process_data_events()

        self.assertFalse(connection.scheduled_reload)

    @mute_logger(POOL_LOGGER)
    def test_heartbeat_timeout_schedules_reload(self):
        connection = self._start()
        connection.raise_on_process = pika.exceptions.AMQPHeartbeatTimeout()

        self.pool.process_data_events()

        self.assertTrue(connection.scheduled_reload)

    @mute_logger(POOL_LOGGER)
    def test_consumer_cancelled_schedules_reload(self):
        """The consumer-specific one: the socket still looks alive, but the
        broker has stopped delivering, so only re-subscribing recovers it."""
        connection = self._start()
        connection.raise_on_process = pika.exceptions.ConsumerCancelled()

        self.pool.process_data_events()

        self.assertTrue(connection.scheduled_reload)

    @mute_logger(POOL_LOGGER)
    def test_stream_lost_schedules_reload(self):
        """Half-open sockets surface as an AMQPError rather than a heartbeat
        timeout, which is why the broad branch exists."""
        connection = self._start()
        connection.raise_on_process = pika.exceptions.StreamLostError()

        self.pool.process_data_events()

        self.assertTrue(connection.scheduled_reload)

    def test_closed_channel_schedules_reload(self):
        connection = self._start()
        connection._channel = FakeChannel(is_closed=True)

        self.pool.process_data_events()

        self.assertTrue(connection.scheduled_reload)

    # ------------------------------------------------------------- reconnect

    def test_scheduled_reload_rebuilds_on_unchanged_config(self):
        """The coupling that makes recovery work.

        Nothing reads ``scheduled_reload`` to reconnect. The rebuild happens
        because the flag changed the connection's config, so the next
        comparison against the database config no longer matches.
        """
        connection = self._start()
        connection.schedule_reload()

        self.pool.update_config(self._db_config())

        self.assertEqual(connection.close_count, 1, "the dead connection is closed")
        self.assertIsNot(
            self.pool.get(CONN_ID), connection, "a new connection replaces it"
        )
        self.assertEqual(len(self.built), 2)
        self.assertFalse(
            self.pool.get(CONN_ID).scheduled_reload,
            "the replacement starts clean",
        )

    def test_unchanged_config_keeps_the_same_connection(self):
        """The other half: without a scheduled reload, the 2-second tick must
        not churn healthy connections."""
        connection = self._start()

        self.pool.update_config(self._db_config())

        self.assertIs(self.pool.get(CONN_ID), connection)
        self.assertEqual(connection.close_count, 0)
        self.assertEqual(len(self.built), 1)

    def test_changed_config_rebuilds(self):
        connection = self._start()
        config = self._db_config()
        config[CONN_ID]["connection_url"] = "amqp://guest:guest@otherhost:5672/"

        self.pool.update_config(config)

        self.assertEqual(connection.close_count, 1)
        self.assertIsNot(self.pool.get(CONN_ID), connection)

    def test_connection_dropped_from_config_is_closed(self):
        connection = self._start()

        self.pool.update_config({})

        self.assertEqual(connection.close_count, 1)
        self.assertIsNone(self.pool.get(CONN_ID))
        self.assertEqual(self.pool.active_connection_ids, [])

    @mute_logger(POOL_LOGGER)
    def test_broken_connection_recovers_end_to_end(self):
        """Failure -> detection -> rebuild, the way a worker cycle runs it."""
        connection = self._start()
        connection.raise_on_process = pika.exceptions.AMQPHeartbeatTimeout()

        self.pool.process_data_events()  # worker cycle: detect
        self.pool.update_config(self._db_config())  # worker cycle: reload tick

        replacement = self.pool.get(CONN_ID)
        self.assertIsNot(replacement, connection)
        self.assertFalse(replacement.scheduled_reload)

        # And the replacement is healthy: another cycle leaves it alone.
        self.pool.process_data_events()
        self.pool.update_config(self._db_config())
        self.assertIs(self.pool.get(CONN_ID), replacement)
