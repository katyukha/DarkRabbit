import logging

import pika

DEFAULT_PROCESS_EVENTS_TIME_LIMIT = 0.2

_logger = logging.getLogger(__name__)


class DarkRabbitConnectionBase:
    """Wrapper around pika connection.
    Automatically opens single channel for connections.

    :param dict config: Configuration for this connections.
        It is expected that config contains `connection_url` and
        `connection_id` keys.
    """

    def __init__(self, config):
        self._config = config

        self._connection = None
        self._channel = None

        # By default connection is sasspendend.
        # First access to connection or channel will automatically
        # establish connection to rabbit. Thus at start we could mark this
        # connection as suspended
        self._suspended = True

    @property
    def connection_id(self):
        return self._config["connection_id"]

    @property
    def connection(self):
        if self._connection is None:
            self.connect()
        return self._connection

    @property
    def channel(self):
        if self._channel is None:
            self.connect()
        return self._channel

    @property
    def config(self):
        return self._config

    @property
    def scheduled_reload(self):
        return self._config.get("dark-connection-reload", False)

    @property
    def suspended(self):
        return self._suspended

    def connect(self):
        self._connection = pika.BlockingConnection(
            pika.URLParameters(self._config["connection_url"])
        )
        self._channel = self.connection.channel()
        self._suspended = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, value, traceback):
        self.close()

    def close(self):
        if self._channel is not None and not self._channel.is_closed:
            self._channel.close()

        if self._connection is not None and not self._connection.is_closed:
            self._connection.close()

    def suspend(self):
        """Suspend connection.
        Closes pika connection and switches dark connection to suspeneded state.

        Connection will resume, on first call to *connection* property
        """
        self.close()
        self._connection = None
        self._channel = None
        self._suspended = True

    def process_data_events(self, time_limit=DEFAULT_PROCESS_EVENTS_TIME_LIMIT):
        """Process data events (heartbeats, etc)"""
        if not self.suspended:
            self.connection.process_data_events(time_limit=time_limit)

    def schedule_reload(self):
        """Schedule reloading of this connection"""
        # We just modify config, thus on next connection reload, it will
        # differ, and dark rabbit will try to reload it.
        self._config["dark-connection-reload"] = True
