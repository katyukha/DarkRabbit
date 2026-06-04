import logging

import pika

DEFAULT_PROCESS_EVENTS_TIME_LIMIT = 0.2
DEFAULT_PIKA_HEARTBEAT = 60

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

        # By default connection is suspendend.
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
        if self._channel is not None and not self._channel.is_closed:
            # It seems that connection already established. No further work needed.
            return

        params = pika.URLParameters(self._config["connection_url"])
        # heartbeat=None means "accept whatever the server proposes" —
        # if the server is configured with heartbeat=0, detection is
        # silently disabled. heartbeat=0 explicitly disables it too.
        # In both cases enforce a minimum so dead TCP connections are
        # always detected regardless of server configuration.
        if not params.heartbeat:
            params.heartbeat = DEFAULT_PIKA_HEARTBEAT
        self._connection = pika.BlockingConnection(params)
        self._channel = self.connection.channel()

        # TODO: Move binding and declare to separate method,
        #       and call only once (at least for publisher)
        self._declare_exchanges()
        self._declare_queues()
        self._apply_queue_bindings()

        self._suspended = False

    def _declare_exchanges(self):
        if declare_exchanges := self._config.get("declare", {}).get("exchanges"):
            for exchange in declare_exchanges:
                self.channel.exchange_declare(
                    exchange=exchange["name"],
                    exchange_type=exchange["type"],
                    durable=exchange["durable"],
                )

    def _declare_queues(self):
        if declare_queues := self._config.get("declare", {}).get("queues"):
            for queue in declare_queues:
                declare = queue.get("queue_declare", {})
                arguments = {}
                if declare_dlx := declare.get("dlx"):
                    arguments["x-dead-letter-exchange"] = declare_dlx
                if declare_dlq_routing := declare.get("dlq_routing"):
                    arguments["x-dead-letter-routing-key"] = declare_dlq_routing
                self.channel.queue_declare(
                    queue=queue["queue_name"],
                    durable=declare["durable"],
                    exclusive=declare["exclusive"],
                    auto_delete=declare["auto_delete"],
                    arguments=arguments if arguments else None,
                )

    def _apply_queue_bindings(self):
        if queue_bindings := self._config.get("declare", {}).get("queue_bindings"):
            for qb in queue_bindings:
                if qb.get("bind", True):
                    self.channel.queue_bind(
                        queue=qb["queue_name"],
                        exchange=qb["exchange_name"],
                        routing_key=qb["routing_key"],
                    )
                else:
                    self.channel.queue_unbind(
                        queue=qb["queue_name"],
                        exchange=qb["exchange_name"],
                        routing_key=qb["routing_key"],
                    )

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
