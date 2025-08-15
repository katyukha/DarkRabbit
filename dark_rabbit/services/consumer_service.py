from odoo.addons.generic_background_service import BackgroundService

from .consumer_worker import DarkRabbitConsumerWorker


class DarkRabbitConsumerService(BackgroundService):
    _name = "dark.rabbit.consumer.service"

    def get_worker_class(self):
        return DarkRabbitConsumerWorker
