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

    def publish(
        self,
        exchange,
        routing_key,
        body,
        message_id=None,
        correlation_id=None,
        timestamp=None,
        message_type=None,
        content_type=None,
    ):
        """Publish message"""
        props = pika.BasicProperties(
            delivery_mode=pika.DeliveryMode.Persistent,
        )
        if message_id:
            props.message_id = message_id
        if correlation_id:
            props.correlation_id = correlation_id
        if timestamp:
            props.timestamp = timestamp
        if message_type:
            props.type = message_type
        if content_type:
            props.content_type = content_type

        self.channel.basic_publish(
            exchange=exchange,
            routing_key=routing_key,
            body=body,
            properties=props,
        )
        self._last_publish = time.time()

    def process_data_events(self, *args, **kwargs):
        super().process_data_events(*args, **kwargs)

        if self._last_publish and time.time() - self._last_publish > SUSPEND_TIMEOUT:
            # Automatically suspend connection, when there no publish events
            # more then SUSPEND_TIMEOUT time
            self.suspend()
