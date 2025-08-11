import logging

import pika

DEFAULT_PREFETCH_COUNT = 3
DEFAULT_PROCESS_EVENTS_TIME_LIMIT = 0.2

_logger = logging.getLogger(__name__)


class DarkRabbitMessage:
    """ Just a wrapper for RabbitMQ message
    """
    def __init__(self, channel, method, properties, body, connection_id, queue_id, handler_id):
        self.channel = channel
        self.method = method
        self.properties = properties
        self.body = body
        self.connection_id = connection_id
        self.queue_id = queue_id
        self.handler_id = handler_id

    def ack(self):
        self.channel.basic_ack(delivery_tag=message.method.delivery_tag)

    def nack(self, requeue=True):
        self.channel.basic_nack(delivery_tag=message.method.delivery_tag, requeue=requeue)

    def __str__(self):
        return (
            f"cid={self.connection_id}, qid={self.queue_id}, hid={self.handler_id}, cn={self.channel}, "
            f"meth={self.method}, props={self.properties}, body={self.body}"
        )


class DarkRabbitCallBack:
    """ Wrapper around callbacks to provide extrainfo (connection and queue)
    """
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
            self._handler_id)
        return self._callback(message)


class DarkRabbitConsumer:
    """ For each connection, we run single consumer,
        that is responnsible for handling all the messages
    """

    # TODO: Move prefetch coung in connection or queue config
    def __init__(self, consumer_config, callback_on_message, prefetch_count=DEFAULT_PREFETCH_COUNT):
        self._config = consumer_config
        self._connection = pika.BlockingConnection(
            pika.URLParameters(self._config['connection_url']))
        self._channel = self._connection.channel()
        self._channel.basic_qos(prefetch_count=prefetch_count)

        self._callback_on_message = callback_on_message

        self._delivery_tags = []

        # Configure listening on specified queues
        for queue_config in self._config['listen_queues']:
            if declare := queue_config.get('queue_declare'):
                self.channel.queue_declare(
                    queue=queue_config['queue_name'],
                    durable=declare['durable'],
                    exclusive=declare['exclusive'],
                    auto_delete=declare['auto_delete'])

            for binding in queue_config.get('bindings', []):
                self.channel.queue_bind(
                    queue=queue_config['queue_name'],
                    exchange=binding['exchange_name'],
                    routing_key=binding['routing_key'])

            self._delivery_tags += self.channel.basic_consume(
                queue=queue_config['queue_name'],
                on_message_callback=DarkRabbitCallBack(
                    connection_id=self._config['connection_id'],
                    queue_id=queue_config['queue_id'],
                    handler_id=queue_config['handler_id'],
                    callback=self._on_message,
                ),
                exclusive=queue_config['listen_exclusive'],
                auto_ack=False,
            )

    @property
    def connection_id(self):
        return self._config['connection_id']

    @property
    def connection(self):
        return self._connection

    @property
    def channel(self):
        return self._channel

    @property
    def listened_queues(self):
        return self._listened_queues

    @property
    def config(self):
        return self._config

    def __enter__(self):
        return self

    def __exit__(self, exc_type, value, traceback):
        self.close()

    def close(self):
        if not self._channel.is_closed:
            self._channel.close()

        if not self._connection.is_closed:
            self._connection.close()

    def _on_message(self, message):
        try:
            self._callback_on_message(message)
        except Exception:
            _logger.error("Cannot process message %s", message, exc_info=True)
            message.nack()
        else:
            message.ack()

    def schedule_reload(self):
        self._config['dark-consumer-reload'] = True

    def poll_events(self, time_limit=DEFAULT_PROCESS_EVENTS_TIME_LIMIT):
        self.connection.process_data_events(time_limit=time_limit)

