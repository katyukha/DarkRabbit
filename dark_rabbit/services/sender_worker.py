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

PublishResult = collections.namedtuple("PublishResult", ["total", "sent", "failed"])


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

    def on_shutdown(self):
        # Close all connections on shutdown
        self._publisher_registry.close_all()

    def _publish_event(self, publisher, event):
        """Publish event and return resyult of publish operation:

        :return: False on error, None on skipped event, True on success
        """
        try:
            publisher.publish(event.exchange, event.routing_key, event.body)
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

    def _publish_events(self, env):
        events = env["dark.rabbit.outgoing.event"].search(
            [
                ("sent_at", "=", False),
                ("connection_id", "in", self._publisher_registry.active_connection_ids),
            ],
            order="created_at ASC",
            limit=BATCH_PUBLISH,
        )
        events_total = len(events)
        events_sent = 0
        events_failed = 0
        events_skipped = 0
        for event in events:
            publisher = self._publisher_registry.get(event.connection_id.id)
            if not publisher:
                # There is not active publisher for this event. Thus we have to
                # skip it. May be publisher for this evetn will be spawned later.
                events_skipped += 1
                continue

            if publisher.scheduled_reload:
                # Publisher is scheduled for reload, thus do not send events to
                # that publisher anymore
                events_skipped += 1
                continue

            if publisher.channel.is_closed:
                # If channel connection is closed, then schedule reload of
                # publisher and skip event
                publisher.schedule_reload()
                events_skipped += 1
                continue

            # Do actual publish of event
            if self._publish_event(publisher, event):
                events_sent += 1
            else:
                events_failed += 1

        return PublishResult(events_total, events_sent, events_failed)

    def publish_events(self):
        """Try to publish batch of events

        :return: PublishResult(total, sent, failed)
        """
        with self.with_env() as env:
            return self._publish_events(env)

    def run_service(self):
        # Reload consumers if needed
        if (
            self._reload_timestamp
            and time.time() - self._reload_timestamp > RELOAD_PERIOD
        ):
            self.reload_publishers()

        while not self._worker_event_stop.is_set():
            # Process Data Events. Do all necessary rabbit routines
            # (heartbeats, etc)
            self._publisher_registry.process_data_events()

            # Try to publish batch of events
            publish_res = self.publish_events()

            if not publish_res.total:
                # We do not publish any event, so it seems that event queue is
                # empty. Thus we can sleep for some time.
                break
