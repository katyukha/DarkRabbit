from odoo.addons.generic_background_service import BackgroundService

from .consumer_worker import DarkRabbitConsumerWorker


class DarkRabbitConsumerService(BackgroundService):
    _name = "dark.rabbit.consumer.service"
    _require_module = "dark_rabbit"

    def get_worker_class(self):
        return DarkRabbitConsumerWorker
