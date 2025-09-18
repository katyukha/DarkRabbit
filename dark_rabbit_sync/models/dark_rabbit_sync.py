import datetime

from odoo import _, api, models

from odoo.addons.dark_rabbit import dark_rabbit_handler


class DarkRabbitSyncException(Exception):
    pass


class DarkRabbitSync(models.AbstractModel):
    _name = "dark.rabbit.sync"
    _inherit = [
        "generic.mixin.track.changes",
    ]

    # TODO: may be it have sense to add field `version` that
    # could be used to distinguish record
    # version, in case when we have two-way sync, this will allow to
    # avoid infinite recursion of changes
    # may be this field should contain also instance id.

    # It is required to specify list of fields to track for changes.
    _dark_rabbit_sync_fields = []

    # We have to specify what field we have to use for sync.
    # TODO: Validate that this field exists, and that it has unique constraint
    _dark_rabbit_sync_key = None

    # Use this event type to send sync events
    # TODO: Generate event type for outgoing events automatically.
    _dark_rabbit_sync_event_type = "dark.rabbit.sync.event"

    def _dark_rabbit_sync_get_fields(self):
        """Return set of fields to be synced by dark rabit"""
        return set(self._dark_rabbit_sync_fields) | {self._dark_rabbit_sync_key}

    def _dark_rabbit_sync_get_source_key(self):
        """Compute source key, to distinguish events from same instance"""
        import hashlib

        dbid = self.sudo().env["ir.config_parameter"].get_param("database.uuid")
        return hashlib.sha1(dbid).digest

    def _dark_rabbit_sync_ensure_model_support(self, model_name):
        """Ensure that model `model_name` supports `dark_rabbit sync protocol"""
        if not hasattr(self.env[model_name], "_dark_rabbit_sync_key"):
            raise TypeError(
                f"Model {model_name} does not support dark.rabbit.sync protocol"
            )

    def _dark_rabbit_sync_serialize_m2o(self, field):
        self._dark_rabbit_sync_ensure_model_support(field.comodel_name)
        value = self[field.name]
        if not value:
            return None
        return value[value._dark_rabbit_sync_key]

    def _dark_rabbit_sync_deserialize_m2o(self, field, value):
        self._dark_rabbit_sync_ensure_model_support(field.comodel_name)

        if not value:
            return None

        comodel = self.env[field.comodel_name]
        result = comodel.with_context(active_test=False).search(
            [(comodel._dark_rabbit_sync_key, "=", value)]
        )
        if not result:
            raise DarkRabbitSyncException(
                _(
                    "Related record %(name)s not found for model %(model)s",
                    name=value,
                    model=field.comodel_name,
                )
            )

        return result

    def _dark_rabbit_sync_serialize(self, sync_fields):
        """Serialize record to be synced to data suitable to pack in JSON

        :param set|list|tuple sync_fields: fields to be synced. Could be empty list.
        """
        result = {}
        for field_name in sync_fields:
            field = self._fields[field_name]
            value = self[field_name]
            if field.type in ("date", "datetime"):
                value = value.isoformat() if value else None
            elif field.type == "many2one":
                value = self._dark_rabbit_sync_serialize_m2o(field)
            # TODO: Add keys for m2o and x2m fields,
            #       and check that related model
            #       also has configured dr sync
            result[field_name] = value
        return result

    def _dark_rabbit_sync_deserialize(self, sync_data):
        """Deserialize sync event data, and return data suitable for create/write"""
        result = {}
        for field_name in self._dark_rabbit_sync_get_fields():
            if field_name not in sync_data:
                continue

            field = self._fields[field_name]
            value = sync_data[field_name]
            if field.type in ("date", "datetime"):
                value = datetime.datetime.fromisoformat(value) if value else None
            elif field.type == "many2one":
                value = self._dark_rabbit_sync_deserialize_m2o(field, value)
            # TODO: Add keys for m2o and x2m fields,
            #       and check that related model
            #       also has configured dr sync
            result[field_name] = value
        return result

    def _dark_rabbit_sync_wrap_event(self, sync_operation, sync_id, data):
        assert sync_operation in ("create", "update", "delete")
        return {
            "dr_sync_model": self._name,
            "dr_sync_id": sync_id,
            "dr_sync_operation": sync_operation,
            "dr_sync_data": data,
            "dr_sync_source_key": self._dark_rabbit_sync_get_source_key(),
        }

    def _get_generic_tracking_fields(self):
        return (
            super()._get_generic_tracking_fields() | self._dark_rabbit_sync_get_fields()
        )

    @api.model_create_multi
    def create(self, vals):
        records = super().create(vals)
        for record in records:
            self.shout_into_darkness(
                self._dark_rabbit_sync_event_type,
                record._dark_rabbit_sync_wrap_event(
                    sync_operation="create",
                    sync_id=record[self._dark_rabbit_sync_key],
                    data=record._dark_rabbit_sync_serialize(
                        self._dark_rabbit_sync_get_fields(),
                    ),
                ),
                correlation_id=record[self._dark_rabbit_sync_key],
            )
        return records

    def _postprocess_write_changes(self, changes):
        super()._postprocess_write_changes(changes)
        changed_fields = set(self._dark_rabbit_sync_get_fields()) & set(changes)
        if changed_fields:
            self.shout_into_darkness(
                self._dark_rabbit_sync_event_type,
                self._dark_rabbit_sync_wrap_event(
                    sync_operation="update",
                    sync_id=(
                        # We have to track changes of sync key field (if it is updated)
                        # thus, we check if sync_key is in changes,
                        # and in this case use original (old) value.
                        changes[self._dark_rabbit_sync_key].old_val
                        if self._dark_rabbit_sync_key in changes
                        else self[self._dark_rabbit_sync_key]
                    ),
                    data=self._dark_rabbit_sync_serialize(changed_fields),
                ),
                correlation_id=self[self._dark_rabbit_sync_key],
            )

    def unlink(self):
        sync_ids = self.mapped(self._dark_rabbit_sync_key)
        super().unlink()
        for sync_id in sync_ids:
            self.shout_into_darkness(
                self._dark_rabbit_sync_event_type,
                self._dark_rabbit_sync_wrap_event(
                    sync_operation="delete",
                    sync_id=sync_id,
                    data={},
                ),
                correlation_id=sync_id,
            )

    @dark_rabbit_handler("Dark Rabbit Sync Event")
    def _on_dark_rabbit_sync_event(self, event):
        event_data = event.read_as_json()
        Model = self.env[event_data["dr_sync_model"]]
        operation = event_data["dr_sync_operation"]
        sync_id = event_data["dr_sync_id"]
        source_key = event_data["dr_sync_source_key"]
        if source_key == self._dark_rabbit_sync_get_source_key():
            return

        if operation == "delete":
            Model.with_context(active_test=False).search(
                [
                    (self._dark_rabbit_sync_key, "=", sync_id),
                ]
            ).unlink()
        elif operation == "create":
            data = self._dark_rabbit_sync_deserialize(event_data["dr_sync_data"])
            data[self._dark_rabbit_sync_key] = sync_id
            Model.with_context(active_test=False).create(data)
        elif operation == "update":
            record = Model.with_context(active_test=False).search(
                [
                    (self._dark_rabbit_sync_key, "=", sync_id),
                ]
            )
            record.ensure_one()
            record.write(
                self._dark_rabbit_sync_deserialize(
                    event_data["dr_sync_data"],
                ),
            )
        else:
            raise ValueError(f"Unknown operation: {operation}")
