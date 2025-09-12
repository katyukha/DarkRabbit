import logging

from odoo import models

_logger = logging.getLogger(__name__)


class Base(models.AbstractModel):
    _inherit = "base"

    def shout_into_darkness(self, code, message, correlation_id=None, jsonify=True):
        """Shout the message into the darkness and Dark Rabbit will come
            to deliver your message to the destination.

        :param str code: code of message to be sent
        :param any message: message to be sent.
        :param bool jsonify: If jsonify is True, message will be encoded as json automatically.
            Default: True.
        """
        self.sudo().env["dark.rabbit.outgoing.event"].add(
            code,
            message,
            correlation_id=correlation_id,
            jsonify=jsonify,
        )

    # For backward compatibility
    def cry_in_darkness(self, code, message, jsonify=True):
        _logger.warning(
            "Call to `cry_in_darkness` is deprecated. Use `shout_into_dakrness` instead."
        )
        return self.shout_into_darkness(code, message, jsonify=jsonify)
