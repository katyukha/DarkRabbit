import logging

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from ..tools.rabbit_schema_spec import parse_yaml

_logger = logging.getLogger(__name__)


class DarkRabbitSchema(models.Model):
    _name = "dark.rabbit.schema"
    _description = "Dark Rabbit: Schema"
    _order = "name"

    name = fields.Char(required=True, index=True)
    spec = fields.Text(
        string="Spec (YAML)",
        help="YAML definition of the AMQP entities required by this schema.",
    )

    _name_uniq = models.Constraint(
        "UNIQUE(name)",
        "Schema name must be unique.",
    )

    def action_open_fill_schema_wizard(self):
        self.ensure_one()
        return self.env["generic.mixin.get.action"].get_action_by_xmlid(
            "dark_rabbit.action_dark_rabbit_fill_schema_wizard",
            context={"default_schema_id": self.id},
        )

    @api.constrains("spec")
    def _check_spec(self):
        for rec in self:
            if not rec.spec:
                continue
            try:
                parse_yaml(rec.spec)
            except ValueError as exc:
                raise ValidationError(
                    _(
                        "Schema %(name)s: invalid spec — %(error)s",
                        name=rec.name,
                        error=exc,
                    )
                ) from exc
