import logging

import pika.exceptions

from .dark_connection_base import DEFAULT_PROCESS_EVENTS_TIME_LIMIT

_logger = logging.getLogger(__name__)


class DarkConnectionPool:
    """Base class for registries for consumers and publishers

    :param connection_factory: Callable used to create new connection
    :param process_data_events_timelimit: Time limit for 'process_data_events'
        for single connection.
    """

    def __init__(
        self,
        connection_factory,
        process_data_events_timelimit=DEFAULT_PROCESS_EVENTS_TIME_LIMIT,
    ):
        # Connection registry
        # Dict: {conn_id: DarkRabbitConnectionBase}
        self._registry = {}
        self._connection_factory = connection_factory
        self._process_data_events_timelimit = process_data_events_timelimit

    @property
    def active_connection_ids(self):
        """Return list of ids of active connections"""
        return list(self._registry.keys())

    def get(self, connection_id):
        return self._registry.get(connection_id)

    def __getitem__(self, connection_id):
        return self._registry[connection_id]

    def update_config(self, config):
        # Stop connections that are not in provided config
        stop_connection_ids = [
            conn_id for conn_id in self._registry if conn_id not in config
        ]

        # Find connections that have changed configuration and have to be reloaded,
        # and add them to stop list
        for conn_id, conn_config in config.items():
            conn = self._registry.get(conn_id, None)
            if conn is None:
                # Connection is not started yet
                continue

            # We have to restart connections that changed configuration
            if conn.config != conn_config:
                stop_connection_ids += [conn_id]

        # Stop connections that have to be stopped
        for conn_id in stop_connection_ids:
            self._registry[conn_id].close()
            del self._registry[conn_id]

        # Spawn missing connections
        for conn_id, conn_config in config.items():
            if conn_id in self._registry:
                # Nothing todo, connection already running
                continue

            try:
                connection = self._connection_factory(conn_config)
            except Exception:
                _logger.error("Cannot spawn connection %s", conn_id, exc_info=True)
                continue

            self._registry[conn_id] = connection

    def close_all(self):
        for connection in self._registry.values():
            connection.close()

    def process_data_events(self):
        """Trigger process data events"""
        for connection in self._registry.values():
            if not connection.suspended and connection.channel.is_closed:
                # If channel connection is closed, then schedule reload of
                # connection
                connection.schedule_reload()
                continue

            try:
                connection.process_data_events(
                    time_limit=self._process_data_events_timelimit
                )
            except pika.exceptions.AMQPHeartbeatTimeout:
                _logger.error(
                    "Heartbeat timeout on connection %s —"
                    " TCP connection is dead, scheduling reload",
                    connection.connection_id,
                    exc_info=True,
                )
                connection.schedule_reload()
            except pika.exceptions.ConsumerCancelled:
                # The broker cancelled the consumer (queue deleted, cluster
                # node failover, ...). The TCP connection may still look alive
                # on our side, but no messages will be delivered anymore, so we
                # have to reload the connection to re-subscribe to the queues.
                _logger.error(
                    "Consumer cancelled by broker on connection %s —"
                    " scheduling reload to re-subscribe",
                    connection.connection_id,
                    exc_info=True,
                )
                connection.schedule_reload()
            except pika.exceptions.AMQPError:
                # Any other AMQP-level error means the connection/channel is no
                # longer usable. Most notably, a half-open TCP socket usually
                # surfaces here as StreamLostError / ConnectionClosed rather
                # than as a heartbeat timeout, so without this branch such a
                # dead connection would propagate and stay a "ghost". Schedule
                # a reload to rebuild it.
                _logger.error(
                    "AMQP error on connection %s — scheduling reload",
                    connection.connection_id,
                    exc_info=True,
                )
                connection.schedule_reload()
            except ValueError as e:
                _logger.error(
                    "Error while processing events (conn_id=%s)",
                    connection.connection_id,
                    exc_info=True,
                )
                if str(e) == "Timeout closed before call":
                    connection.schedule_reload()
                    continue
                raise
