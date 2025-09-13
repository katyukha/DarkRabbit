from odoo import fields, models


class TestDarkRabbitSyncRecord(models.Model):
    _name = "test.dark.rabbit.sync.record"
    _inherit = [
        "generic.mixin.uuid",
        "dark.rabbit.sync",
        "dark.rabbit.handler.mixin",
    ]

    _generic_mixin_uuid_field_name = "uuid"

    _dark_rabbit_sync_fields = [
        "dt",
        "text",
    ]
    _dark_rabbit_sync_key = "uuid"

    uuid = fields.Char(
        index=True,
        required=True,
        readonly=True,
        size=38,
        default="/",
        copy=False,
        string="UUID",
    )

    dt = fields.Datetime(default=fields.Datetime.now, required=True, index=True)
    text = fields.Text()
