import time

import pika

from .dark_connection_base import DarkRabbitConnectionBase

# Time in seconds after last publish to swithc publisher to suspended state
SUSPEND_TIMEOUT = 20

# Message rate recompute interval
MESSAGE_RATE_INTERVAL = 60


class DarkRabbitPublisher(DarkRabbitConnectionBase):
    def __init__(self, config):
        super().__init__(config)

        self._last_publish = None

        # These attributes are used to compute message rate for this publisher
        self._message_count = 0
        self._message_rate_time = time.time()
        self._message_rate_prev = 0

    def _update_message_rate(self):
        if (time.time() - self._message_rate_time) <= MESSAGE_RATE_INTERVAL:
            # Do nothing, we recompute message rate only once per MESSAGE_RATE_INTERVAL
            return

        self._message_rate_prev = self.message_rate
        self._message_count = 0
        self._message_rate_time = time.time()

    @property
    def message_rate(self):
        """Compute current message rate (of current iteration)"""
        if tdiff := time.time() - self._message_rate_time:
            if tdiff > 0.0005:
                return self._message_count / tdiff
        return 0

    @property
    def throttling_threshold(self):
        return self._config.get("throttling_threshold", 0.0)

    @property
    def can_send(self):
        if self.throttling_threshold:
            mrate = self.message_rate
            if not mrate:
                mrate = self._message_rate_prev
            return mrate < self.throttling_threshold
        return True

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
        headers=None,
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
        if headers:
            props.headers = headers

        self.channel.basic_publish(
            exchange=exchange,
            routing_key=routing_key,
            body=body,
            properties=props,
        )
        self._last_publish = time.time()
        self._message_count += 1

    def process_data_events(self, *args, **kwargs):
        super().process_data_events(*args, **kwargs)

        self._update_message_rate()
        if self._last_publish and time.time() - self._last_publish > SUSPEND_TIMEOUT:
            # Automatically suspend connection, when there no publish events
            # more then SUSPEND_TIMEOUT time
            self.suspend()
