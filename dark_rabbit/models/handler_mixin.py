from odoo import models, fields, api, tools
from odoo.addons.dark_rabbit.tools.dark_handler import find_dark_rabbit_handlers


class DarkRabbitHandlerMixin(models.AbstractModel):
    _name = 'dark.rabbit.handler.mixin'
    _description = 'Dark Rabbit: Handler Mixin'


    def _auto_init(self):
        res = super()._auto_init()

        cls = type(self)

        if cls._abstract:
            # Do not look for handlers on abstract models
            return res

        hmodel_id = self.sudo().env['ir.model']._get(self._name).id
        handler_rows = []
        for method_name, handler_name in find_dark_rabbit_handlers(cls):
            handler_rows += [(hmodel_id, method_name, handler_name)]


        @self.pool.post_init
        def _register_dark_rabbit_handlers():
            self.env.cr.execute(tools.SQL(
                (
                    'INSERT INTO %s (%s) VALUES %s '
                    'ON CONFLICT (model_id, method_name) '
                    'DO UPDATE SET name = EXCLUDED.name '
                    'RETURNING "id"'
                ),
                tools.SQL.identifier(self.env['dark.rabbit.handler']._table),
                tools.SQL(', ').join(map(tools.SQL.identifier, ["model_id", "method_name", "name"])),
                tools.SQL(', ').join(handler_rows),
            ))

        return res
