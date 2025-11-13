from odoo import fields, models


class TestDarkRabbitOutgoingEvent(models.Model):
    _name = "test.dark.rabbit.outgoing.event"

    body = fields.Text(required=True)
    tag_id = fields.Many2one(comodel_name="dark.rabbit.outgoing.routing.tag")

    def create(self, vals):
        records = super().create(vals)
        for rec in records:
            self.shout_into_darkness(
                "test-record-created", {"body": rec.body}, tags=rec.tag_id.code
            )
        return records

    def write(self, vals):
        res = super().write(vals)
        for rec in self:
            self.shout_into_darkness(
                "test-record-updated", {"body": rec.body}, tags=rec.tag_id.code
            )
        return res

    def unlink(self):
        for rec in self:
            self.shout_into_darkness(
                "test-record-deleted", {"body": rec.body}, tags=rec.tag_id.code
            )
        return super().unlink()
