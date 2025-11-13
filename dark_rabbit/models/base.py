import logging
from typing import List

from odoo import models

_logger = logging.getLogger(__name__)


class Base(models.AbstractModel):
    _inherit = "base"

    def shout_into_darkness(
        self,
        code,
        message,
        *,
        correlation_id=None,
        jsonify=True,
        tags: List[str] | str = None
    ):
        """Shout the message into the darkness and Dark Rabbit will come
            to deliver your message to the destination.

        :param str code: code of message to be sent
        :param any message: message to be sent.
        :param bool jsonify: If jsonify is True, message will be encoded as json automatically.
            Default: True.
        :param list[str]|str tags: tag or list of tags,
            that could be used to route this message to correct exchange.
        """
        self.sudo().env["dark.rabbit.outgoing.event"].add(
            code,
            message,
            correlation_id=correlation_id,
            jsonify=jsonify,
            tags=tags,
        )
