import pika

DEFAULT_PROCESS_EVENTS_TIME_LIMIT = 0.2


class DarkRabbitConnectionBase:
    """Wrapper around pika connection.
    Automatically opens single channel for connections.

    :param dict config: Configuration for this connections.
        It is expected that config contains `connection_url` and
        `connection_id` keys.
    """

    def __init__(self, config):
        self._config = config

        self._connection = pika.BlockingConnection(
            pika.URLParameters(self._config["connection_url"])
        )
        self._channel = self._connection.channel()

    @property
    def connection_id(self):
        return self._config["connection_id"]

    @property
    def connection(self):
        return self._connection

    @property
    def channel(self):
        return self._channel

    @property
    def config(self):
        return self._config

    @property
    def scheduled_reload(self):
        return self._config.get("dark-connection-reload", False)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, value, traceback):
        self.close()

    def close(self):
        if not self._channel.is_closed:
            self._channel.close()

        if not self._connection.is_closed:
            self._connection.close()

    def process_data_events(self, time_limit=DEFAULT_PROCESS_EVENTS_TIME_LIMIT):
        self.connection.process_data_events(time_limit=time_limit)

    def schedule_reload(self):
        """Schedule reloading of this connection"""
        # We just modify config, thus on next connection reload, it will
        # differ, and dark rabbit will try to reload it.
        self._config["dark-connection-reload"] = True
