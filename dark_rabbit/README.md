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
