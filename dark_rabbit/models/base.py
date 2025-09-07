from odoo import models


class Base(models.AbstractModel):
    _inherit = "base"

    def cry_in_darkness(self, code, message):
        """Cry message in darkness, and hope that somebody will here you.

        :param str code: code of message to be sent
        :param str message: text message to be sent
        """
        self.sudo().env["dark.rabbit.outgoing.event"].add(
            code,
            message,
        )
