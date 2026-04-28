# DarkRabbit

RabbitMQ integration powered by small piece of Dark Magic. Enjoy ;)

## Installation

In order to allow DarkRabbit to work, it is required to specify it in `server_wide_modules` parameter in Odoo config.
This way, it will run all the magic in background.

To do this, add following line to your Odoo configuration file:

```
server_wide_modules = base,web,generic_background_service,dark_rabbit
```

DarkRabbit will be summoned inside ~~pentagram~~container provided by [`generic_background_service`](https://github.com/crnd-inc/generic-background-service) module.

## Schemas

A **schema** is a named, declarative description of the AMQP entities (exchanges, queues, bindings) that an integration requires.
Schemas are stored as `dark.rabbit.schema` records and defined in YAML.
They do not replace the existing exchange/queue/binding records — instead they act as a reconciler:
applying a schema creates missing entities and updates drifted fields on existing ones.

### Applying a schema

Open a connection record and click **Apply Schema** in the header.
Select one or more schemas, then click **Apply**.

Before writing anything the wizard:
1. Parses each schema's YAML spec.
2. Merges all selected schemas into a single topology.
3. Validates the merge — if two schemas declare the same entity with incompatible configuration an error is raised and nothing is written.
4. Reconciles the merged topology against the connection's existing DB records.

Multiple schemas can be applied to the same connection (e.g. one schema per integration point).

### Shipping a schema with an addon

Define a `dark.rabbit.schema` record in your addon's XML data:

```xml
<record id="my_integration_schema" model="dark.rabbit.schema">
    <field name="name">my.integration</field>
    <field name="spec"><![CDATA[
exchanges:
  - name: my.events
    type: topic
    durable: true

queues:
  - name: my.tasks
    durable: true
    dlx: dead.letters
    dlq_routing: my.tasks.dead
    bindings:
      - exchange: my.events
        routing_key: "my.tasks.*"
    ]]></field>
</record>
```

### Schema YAML format

```yaml
exchanges:
  - name: <string>          # required — AMQP exchange name
    declare: <bool>         # default: true — whether to declare to RabbitMQ on connect
    type: <string>          # default: topic — topic | direct | fanout | headers
    durable: <bool>         # default: true

queues:
  - name: <string>          # required — AMQP queue name
    declare: <bool>         # default: true
    durable: <bool>         # default: true
    exclusive: <bool>       # default: false
    auto_delete: <bool>     # default: false
    dlx: <string>           # optional — dead-letter exchange name (must exist on the connection)
    dlq_routing: <string>   # optional — dead-letter routing key
    bindings:
      - exchange: <string>  # required — exchange name (must exist on the connection)
        routing_key: <string>  # default: ""
```

**Merge rules** (when multiple schemas are applied together):

| Situation | Behaviour |
|---|---|
| Same exchange/queue name, identical config | Merged silently (idempotent) |
| Same exchange name, different `type` or `durable` | **Conflict error** — nothing written |
| Same queue name, different structural fields | **Conflict error** — nothing written |
| Same exchange/queue, one has `declare: true` | `declare: true` wins (OR semantics) |
| Same binding `(queue, exchange, routing_key)` | Deduplicated — created once |

`listen` and `handler_id` are intentionally absent from the schema format — they are consumer configuration, not topology.
