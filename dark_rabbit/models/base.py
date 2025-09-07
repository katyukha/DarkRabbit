import json

from odoo import models


class Base(models.AbstractModel):
    _inherit = "base"

    def cry_in_darkness(self, code, message, jsonify=True):
        """Cry message in darkness, and hope that somebody will here you.

        :param str code: code of message to be sent
        :param any message: message to be sent.
        :param bool jsonify: If jsonify is True, message will be encoded as json automatically.
            Default: True.
        """
        if jsonify:
            message = json.dumps(message)

        self.sudo().env["dark.rabbit.outgoing.event"].add(
            code,
            message,
        )
