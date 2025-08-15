import logging

from odoo.addons.generic_background_service import AbstractBackgroundServiceWorker

_logger = logging.getLogger(__name__)

# Every RELOAD_PERIOD seconds, worker will check that database for
# configuration changes, and reload or drop sender if configuration changes.
RELOAD_PERIOD = 2  # seconds

# POLLING_CYCLE_INTERVAL represents the timeout between event polling cycles
POLLING_CYCLE_INTERVAL = 0.3  # seconds


class DarkRabbitSenderWorker(AbstractBackgroundServiceWorker):
    """This class represents service worker for single database.

    It is responsible for reading info about connections,
    and spawning rabbit sender in separate threads for each
    'dark.rabbit.connection'.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Sender registry
        # Dict: {conn_id: DarkRabbitConsumer}
        self._sender_registry = {}

        self._reload_timestamp = None

    def get_sleep_timeout(self):
        # The time between polling cycles (Calls to run_service)
        return POLLING_CYCLE_INTERVAL

    def on_init(self):
        # We have to reload consumers on init
        self.reload_senders()

    def reload_senders(self):
        return

    def on_shutdown(self):
        for sender in self._senders_registry.values():
            sender.close()

    def run_service(self):
        return
