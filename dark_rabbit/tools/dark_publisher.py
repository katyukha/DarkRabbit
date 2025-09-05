import pika

from .dark_connection_base import DarkRabbitConnectionBase


class DarkRabbitPublisher(DarkRabbitConnectionBase):
    def __init__(self, config):
        super().__init__(config)

        self._channel.confirm_delivery()

    def publish(self, exchange, routing_key, body):
        """Publish message"""
        self._channel.basic_publish(
            exchange=exchange,
            routing_key=routing_key,
            body=body,
            properties=pika.BasicProperties(delivery_mode=pika.DeliveryMode.Persistent),
        )

    # TODO: override process_data_events, and use calls of that method as
    # heartbeats. Close connection if it is not active for more then 60
    # seconds. And automatically reconnect to rabbit on publish.
    # This way we will be able to run only connections that are in use.
