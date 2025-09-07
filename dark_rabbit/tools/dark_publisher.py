import time

import pika

from .dark_connection_base import DarkRabbitConnectionBase

# Time in seconds after last publish to swithc publisher to suspended state
SUSPEND_TIMEOUT = 20


class DarkRabbitPublisher(DarkRabbitConnectionBase):
    def __init__(self, config):
        super().__init__(config)

        self._last_publish = None

    def connect(self):
        super().connect()
        self.channel.confirm_delivery()

    def publish(self, exchange, routing_key, body):
        """Publish message"""
        self.channel.basic_publish(
            exchange=exchange,
            routing_key=routing_key,
            body=body,
            properties=pika.BasicProperties(delivery_mode=pika.DeliveryMode.Persistent),
        )
        self._last_publish = time.time()

    # TODO: override process_data_events, and use calls of that method as
    # heartbeats. Close connection if it is not active for more then 60
    # seconds. And automatically reconnect to rabbit on publish.
    # This way we will be able to run only connections that are in use.

    def process_data_events(self, *args, **kwargs):
        super().process_data_events(*args, **kwargs)

        if self._last_publish and time.time() - self._last_publish > SUSPEND_TIMEOUT:
            self.suspend()
