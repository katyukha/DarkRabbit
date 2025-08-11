import threading
import logging
import collections
import time

from odoo.addons.generic_background_service import (
    AbstractBackgroundServiceWorker,
)
from odoo.addons.dark_rabbit.tools.dark_consumer import DarkRabbitConsumer

_logger = logging.getLogger(__name__)

# Every RELOAD_PERIOD seconds, worker will check that database for
# configuration changes, and reload or drop consumers if configuration changes.
RELOAD_PERIOD = 2  # seconds

# POLLING_CYCLE_INTERVAL represents the timeout between event polling cycles
POLLING_CYCLE_INTERVAL = 0.3  # seconds


class DarkRabbitWorker(AbstractBackgroundServiceWorker):
    """ This class represents service worker for single database.

        It is responsible for reading info about connections,
        and spawning rabbit consumers in separate threads for each
        'dark.rabbit.connection'.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Consumer registry
        # Dict: {conn_id: DarkRabbitConsumer}
        self._consumer_registry = {}

        self._reload_timestamp = None

    def get_sleep_timeout(self):
        # The time between polling cycles (Calls to run_service)
        return POLLING_CYCLE_INTERVAL

    def on_init(self):
        # We have to reload consumers on init
        self.reload_consumers()

    def reload_consumers(self):
        with self.with_env() as env:
            connections_map = {
                c.id: c.get_consumer_config()
                for c in env['dark.rabbit.connection'].search([
                    ('queue_ids.listen', '=', True),
                ])
            }

        # Stop consumers that are not in active connections
        stop_connection_ids = [
            conn_id
            for conn_id in self._consumer_registry
            if conn_id not in connections_map
        ]

        # Find consumers that have changed configuration and have to be reloaded,
        # and add them to stop list
        for conn_id, conn_config in connections_map.items():
            consumer = self._consumer_registry.get(conn_id, None)
            if consumer is None:
                # Consumer is not started yet
                continue

            # We have to restart connections that changed queues
            # configuration
            if consumer.config != conn_config:
                stop_connection_ids += [conn_id]

        # Stop consumers that have to be stopped
        for conn_id in stop_connection_ids:
            self._consumer_registry[conn_id].close()
            del self._consumer_registry[conn_id]

        # Spawn missing consumers
        for conn_id, conn_config in connections_map.items():
            if conn_id in self._consumer_registry:
                # Nothing todo, consumer already running
                continue

            try:
                consumer = DarkRabbitConsumer(
                    consumer_config=conn_config,
                    callback_on_message=self._on_message,
                )
            except Exception:
                _logger.error("Cannot spawn consumer for connection %s", conn_id, exc_info=True)
                continue

            self._consumer_registry[conn_id] = consumer
        self._reload_timestamp = time.time()

    def on_shutdown(self):
        for consumer in self._consumer_registry.values():
            consumer.close()

    def _on_message(self, message):
        with self.with_env() as env:
            env['dark.rabbit.event'].handle_message(message)

    def run_service(self):
        # Reload consumers if needed
        if self._reload_timestamp and time.time() - self._reload_timestamp > RELOAD_PERIOD:
            self.reload_consumers()

        for conn_id, consumer in self._consumer_registry.items():
            if self._worker_event_stop.is_set():
                # Exit fast if stop event received
                break

            if consumer.channel.is_closed:
                # If channel connection is closed, then schedule reload of
                # consumer.
                consumer.schedule_reload()
                continue

            # Do the actual poll events
            try:
                consumer.poll_events()
            except ValueError as e:
                _logger.error("Error while polling events (conn_id=%s)", conn_id, exc_info=True)
                if str(e) == "Timeout closed before call":
                    # It seems that connection was closed, so in this case we
                    # just schedule connection reload
                    consumer.schedule_reload()
                    continue
                else:
                    raise
            except Exception:
                _logger.error("Error while polling events (conn_id=%s)", conn_id, exc_info=True)
                raise
