from odoo.addons.generic_background_service import BackgroundService

from .worker import DarkRabbitWorker


class DarkRabbitService(BackgroundService):
    _name = 'dark.rabbit.service'

    def get_worker_class(self):
        return DarkRabbitWorker
