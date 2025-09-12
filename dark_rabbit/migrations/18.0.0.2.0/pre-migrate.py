from odoo.addons.generic_mixin.tools.uuid import auto_generate_uuids, create_uuid_field


def migrate(cr, version):
    create_uuid_field(cr, "dark_rabbit_outgoing_event", "message_id")
    auto_generate_uuids(cr, "dark_rabbit_outgoing_event", "message_id")
