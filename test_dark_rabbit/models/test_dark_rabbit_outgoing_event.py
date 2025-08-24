from odoo import fields, models

# from odoo.addons.dark_rabbit.models import dark_rabbit_outgoing_event


class TestDarkRabbitOutgoingEvent(models.Model):
    _name = "test.dark.rabbit.outgoing.event"

    body = fields.Text(required=True)

    def create(self, vals):

        records = super().create(vals)
        for rec in records:
            self.env["dark.rabbit.outgoing.event"].add("test-flight-created", rec.body)
        return records

    def write(self, vals):
        records = super().write(vals)
        for rec in self:
            self.env["dark.rabbit.outgoing.event"].add("test-flight-updated", rec.body)
        return records

    def unlink(self):
        for rec in self:
            self.env["dark.rabbit.outgoing.event"].add("test-flight-deleted", rec.body)
        return super().unlink()
