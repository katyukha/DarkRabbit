from odoo import fields, models


class TestDarkRabbitSyncRelatedRecord(models.Model):
    _name = "test.dark.rabbit.sync.related.record"
    _inherit = [
        "generic.mixin.uuid",
        "dark.rabbit.sync",
        "dark.rabbit.handler.mixin",
    ]

    _generic_mixin_uuid_field_name = "name"

    _dark_rabbit_sync_fields = ["name"]
    _dark_rabbit_sync_key = "name"

    name = fields.Char("Name", required=True)
