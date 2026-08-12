import collections
import datetime
import logging
import time
import traceback

import psycopg2

from odoo.addons.dark_rabbit.tools.dark_connection_pool import DarkConnectionPool
from odoo.addons.dark_rabbit.tools.dark_publisher import DarkRabbitPublisher
from odoo.addons.generic_background_service import AbstractBackgroundServiceWorker

_logger = logging.getLogger(__name__)

# Every RELOAD_PERIOD seconds, worker will check that database for
# configuration changes, and reload or drop consumers if configuration changes.
RELOAD_PERIOD = 2  # seconds

# PUBLISHER_SLEEP_INTERVAL represents the timeout between event polling cycles
PUBLISHER_SLEEP_INTERVAL = 3  # seconds

# How many events we have to send in one batch
BATCH_PUBLISH = 100

# Slowdown timout in seconds. Sleep for specified amount of time,
# if we reached rate limit, or skip too much events
SLOWDOWN_TIMEOUT = 0.3

PublishResult = collections.namedtuple(
    "PublishResult", ["total", "sent", "skipped", "failed"]
)


class DarkRabbitSenderWorker(AbstractBackgroundServiceWorker):
    """This class represents service worker for single database.

    It is responsible for reading info about connections,
    and spawning rabbit sender in separate thread for each
    'dark.rabbit.connection'.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Consumer registry
        # Dict: {conn_id: DarkRabbitPublisher}
        self._publisher_registry = DarkConnectionPool(
            connection_factory=DarkRabbitPublisher
        )

        self._reload_timestamp = None

    def get_sleep_timeout(self):
        # The time between polling cycles (Calls to run_service)
        return PUBLISHER_SLEEP_INTERVAL

    def on_init(self):
        # We have to reload publishers on init
        self.reload_publishers()

    def _get_publisher_config(self):
        # Find connections that need to use publisher
        with self.with_env() as env:
            connections_map = {
                c.id: c.get_publisher_config()
                for c in env["dark.rabbit.connection"].search(
                    [
                        ("outgoing_route_ids", "!=", False),
                    ]
                )
            }
        return connections_map

    def reload_publishers(self):
        try:
            connections_map = self._get_publisher_config()
        except psycopg2.OperationalError:
            _logger.warning(
                "Cannot obtain publishers configuration. "
                "Possibly postgresql is not accessible. "
                "Shutting down all publishers."
            )
            connections_map = {}

        self._publisher_registry.update_config(connections_map)

        self._reload_timestamp = time.time()

    def reload_publishers_if_needed(self):
        if (
            self._reload_timestamp
            and time.time() - self._reload_timestamp > RELOAD_PERIOD
        ):
            self.reload_publishers()

    def on_shutdown(self):
        # Close all connections on shutdown
        self._publisher_registry.close_all()

    def _publish_event(self, publisher, event):
        """Publish event and return resyult of publish operation:

        :return: False on error, None on skipped event, True on success
        """
        # TODO: publish each event in own transaction,
        # to avoid repeating of event sent multiple times
        try:
            timestamp = int(event.timestamp)
        except ValueError:
            # TODO: Do we need to set None here?
            timestamp = None

        try:
            publisher.publish(
                event.exchange,
                event.routing_key,
                event.body,
                message_id=event.message_id,
                correlation_id=event.correlation_id,
                timestamp=timestamp,
                message_type=event.message_type,
                content_type=event.content_type,
            )
        except Exception as exc:
            event.write(
                {
                    "error": True,
                    "error_msg": "".join(traceback.format_exception(exc)),
                }
            )
            return False

        event.write(
            {
                "sent_at": datetime.datetime.now(),
            }
        )
        return True

    def _publisher_ready(self, publisher):
        """Whether ``publisher`` can accept events right now.

        Checked *before* querying: a publisher that cannot send should not cost
        a database round trip at all.
        """
        if not publisher:
            # No publisher spawned for this connection yet; one may appear on a
            # later cycle.
            return False

        if not publisher.can_send:
            return False

        if publisher.scheduled_reload:
            return False

        if publisher.channel.is_closed:
            publisher.schedule_reload()
            return False

        return True

    def _publish_events(self, env):
        """Publish a batch per ready connection.

        Readiness is decided first and events are fetched per connection, so a
        stalled publisher costs nothing -- previously its events were selected
        and then discarded, one query and one batch slot per cycle, every
        cycle.

        Note this makes ``PublishResult.total`` count events actually
        attempted rather than merely selected. ``run_service`` reads it as "is
        there anything to do", so when no publisher is usable it now correctly
        sees zero and sleeps, instead of spinning on events it could never
        send.
        """
        events_total = 0
        events_sent = 0
        events_failed = 0
        events_skipped = 0

        for connection_id in self._publisher_registry.active_connection_ids:
            publisher = self._publisher_registry.get(connection_id)
            if not self._publisher_ready(publisher):
                continue

            # One connection at a time, never `connection_id IN (...)`: this
            # shape matches dark_rabbit_outgoing_event__sender_search_v2__idx,
            # which leads with connection_id and continues with exactly this
            # ordering, so the index answers the filter AND the sort and the
            # scan stops at the limit. An IN list cannot produce the global
            # ordering, so PostgreSQL would sort every matching row first.
            events = env["dark.rabbit.outgoing.event"].search(
                [("sent_at", "=", False), ("connection_id", "=", connection_id)],
                order="created_at ASC, timestamp ASC, id ASC",
                limit=BATCH_PUBLISH,
            )
            events_total += len(events)

            for index, event in enumerate(events):
                if publisher.channel.is_closed:
                    # Channel died part way through the batch. Stop and let the
                    # next cycle retry the remainder against a fresh publisher,
                    # rather than failing every event that is left.
                    publisher.schedule_reload()
                    events_skipped += len(events) - index
                    break

                # Do actual publish of event
                if self._publish_event(publisher, event):
                    events_sent += 1
                else:
                    events_failed += 1

        return PublishResult(events_total, events_sent, events_skipped, events_failed)

    def publish_events(self):
        """Try to publish batch of events

        :return: PublishResult(total, sent, failed)
        """
        with self.with_env() as env:
            return self._publish_events(env)

    def run_service(self):
        while not self._worker_event_stop.is_set():
            # At first we reload publiahsers if needed
            self.reload_publishers_if_needed()

            # Process Data Events. Do all necessary rabbit routines
            # (heartbeats, etc)
            self._publisher_registry.process_data_events()

            # Try to publish batch of events
            publish_res = self.publish_events()

            if publish_res.total and publish_res.sent / publish_res.total < 0.9:
                # It seems that too many events failed. Let's slow down.
                self.sleep(SLOWDOWN_TIMEOUT)

            if not publish_res.total:
                # We do not publish any event, so it seems that event queue is
                # empty. Thus we can sleep for some time.
                break
