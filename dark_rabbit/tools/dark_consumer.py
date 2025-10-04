import logging

from .dark_connection_base import DarkRabbitConnectionBase

DEFAULT_PREFETCH_COUNT = 3

_logger = logging.getLogger(__name__)


class DarkRabbitMessage:
    """Just a wrapper for RabbitMQ message"""

    def __init__(
        self, channel, method, properties, body, connection_id, queue_id, handler_id
    ):
        self.channel = channel
        self.method = method
        self.properties = properties
        self.body = body
        self.connection_id = connection_id
        self.queue_id = queue_id
        self.handler_id = handler_id

    def ack(self):
        self.channel.basic_ack(delivery_tag=self.method.delivery_tag)

    def nack(self, requeue=True):
        self.channel.basic_nack(delivery_tag=self.method.delivery_tag, requeue=requeue)

    def __str__(self):
        return (
            f"cid={self.connection_id}, qid={self.queue_id}, "
            f"hid={self.handler_id}, cn={self.channel}, "
            f"meth={self.method}, props={self.properties}, body={self.body}"
        )


class DarkRabbitCallBack:
    """Wrapper around callbacks to provide extrainfo (connection and queue)"""

    def __init__(self, connection_id, queue_id, handler_id, callback):
        self._connection_id = connection_id
        self._queue_id = queue_id
        self._handler_id = handler_id
        self._callback = callback

    def __call__(self, channel, method, properties, body):
        message = DarkRabbitMessage(
            channel,
            method,
            properties,
            body,
            self._connection_id,
            self._queue_id,
            self._handler_id,
        )
        return self._callback(message)


class DarkRabbitConsumer(DarkRabbitConnectionBase):
    """For each connection, we run single consumer,
    that is responnsible for handling all the messages
    """

    # TODO: Move prefetch count in connection or queue config
    def __init__(
        self,
        consumer_config,
        callback_on_message,
        prefetch_count=DEFAULT_PREFETCH_COUNT,
    ):
        super().__init__(consumer_config)

        # Explicitely start connection
        self.connect()

        # This will start the connection
        self.channel.basic_qos(prefetch_count=prefetch_count)

        self._callback_on_message = callback_on_message

        self._delivery_tags = []

        # # Configure listening on specified queues
        for queue_config in self._config["listen_queues"]:
            self._delivery_tags += self.channel.basic_consume(
                queue=queue_config["queue_name"],
                on_message_callback=DarkRabbitCallBack(
                    connection_id=self._config["connection_id"],
                    queue_id=queue_config["queue_id"],
                    handler_id=queue_config["handler_id"],
                    callback=self._on_message,
                ),
                exclusive=queue_config["listen_exclusive"],
                auto_ack=False,
            )

    @property
    def listened_queues(self):
        return self._listened_queues

    def _on_message(self, message):
        try:
            self._callback_on_message(message)
        except Exception:
            _logger.error("Cannot process message %s", message, exc_info=True)
            message.nack()
            # TODO: Compute fail rate, and if fail rate reaches dangerous
            # values (more than 5 seconds), then nack without requeue.
            # Possibly suspend consumer for some period of time.
        else:
            message.ack()

    def poll_events(self):
        self.process_data_events()
