import logging

from odoo.addons.generic_background_service import AbstractBackgroundServiceWorker

_logger = logging.getLogger(__name__)

# POLLING_CYCLE_INTERVAL represents the timeout between event polling cycles
POLLING_CYCLE_INTERVAL = 10  # seconds


class DarkRabbitSenderWorker(AbstractBackgroundServiceWorker):
    """This class represents service worker for single database.

    It is responsible for reading info about connections,
    and spawning rabbit sender in separate threads for each
    'dark.rabbit.connection'.
    """

    def get_sleep_timeout(self):
        # The time between polling cycles (Calls to run_service)
        return POLLING_CYCLE_INTERVAL

    def run_service(self):
        with self.with_env() as env:

            connections = env["dark.rabbit.connection"].search([])

            for connection in connections:
                events_for_send = env["dark.rabbit.outgoing.event"].search(
                    [
                        ("sent_at", "=", False),
                        ("connection_id", "=", connection.id),
                    ]
                )
                if len(events_for_send) > 0:
                    connection.send(events_for_send)
