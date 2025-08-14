-- deactivate all connections
UPDATE dark_rabbit_connection
   SET active = false;

-- deactivate all queues
UPDATE dark_rabbit_queue
   SET listen = false;
