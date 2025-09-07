from odoo.addons.generic_background_service import BackgroundService

from .sender_worker import DarkRabbitSenderWorker


class DarkRabbitSenderService(BackgroundService):
    _name = "dark.rabbit.sender.service"
    _require_module = "dark_rabbit"

    def get_worker_class(self):
        return DarkRabbitSenderWorker
