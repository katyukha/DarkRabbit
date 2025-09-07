import logging
import time

import psycopg2

from odoo.addons.dark_rabbit.tools.dark_connection_pool import DarkConnectionPool
from odoo.addons.dark_rabbit.tools.dark_consumer import DarkRabbitConsumer
from odoo.addons.generic_background_service import AbstractBackgroundServiceWorker

_logger = logging.getLogger(__name__)

# Every RELOAD_PERIOD seconds, worker will check that database for
# configuration changes, and reload or drop consumers if configuration changes.
RELOAD_PERIOD = 2  # seconds

# POLLING_CYCLE_INTERVAL represents the timeout between event polling cycles
POLLING_CYCLE_INTERVAL = 0.3  # seconds


class DarkRabbitConsumerWorker(AbstractBackgroundServiceWorker):
    """This class represents service worker for single database.

    This worker contains pool of rabbit consumers (each represent separate connection),
    and polls these consumers for events in the loop,
    attempting to read predefined amount of events.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Consumer registry
        # Dict: {conn_id: DarkRabbitConsumer}
        self._consumer_registry = DarkConnectionPool(
            connection_factory=lambda config: DarkRabbitConsumer(
                consumer_config=config,
                callback_on_message=self._on_message,
            )
        )

        self._reload_timestamp = None

    def get_sleep_timeout(self):
        # The time between polling cycles (Calls to run_service)
        return POLLING_CYCLE_INTERVAL

    def on_init(self):
        # We have to reload consumers on init
        self.reload_consumers()

    def _get_consumer_config(self):
        with self.with_env() as env:
            connections_map = {
                c.id: c.get_consumer_config()
                for c in env["dark.rabbit.connection"].search(
                    [
                        ("queue_ids.listen", "=", True),
                    ]
                )
            }
        return connections_map

    def reload_consumers(self):
        try:
            connections_map = self._get_consumer_config()
        except psycopg2.OperationalError:
            _logger.warning(
                "Cannot obtain consumer configuration. Possibly postgresql is not accessible. "
                "Shutting down all consumers."
            )
            connections_map = {}

        self._consumer_registry.update_config(connections_map)
        self._reload_timestamp = time.time()

    def on_shutdown(self):
        self._consumer_registry.close_all()

    def _on_message(self, message):
        with self.with_env() as env:
            env["dark.rabbit.event"].handle_message(message)

    def run_service(self):
        # Reload consumers if needed
        if (
            self._reload_timestamp
            and time.time() - self._reload_timestamp > RELOAD_PERIOD
        ):
            self.reload_consumers()

        self._consumer_registry.process_data_events()
