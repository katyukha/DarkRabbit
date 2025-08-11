import inspect


def dark_rabbit_handler(name):
    """ Mark specified method ad capable of handling dark rabbit events
    """
    def wrapper(fn):
        # TODO: Check signature
        fn.__dark_rabbit_handler_name__ = name
        return fn
    return wrapper


def is_dark_rabbit_handler(func):
    """ Check if method (func) is handler for Dark Rabbit Events
    """
    if not callable(func):
        return False
    if hasattr(func, '__dark_rabbit_handler_name__'):
        return True
    return False


class DarkHandler:
    def __init__(self, method_name, name):
        self.method_name = method_name
        self.name = name


def find_dark_rabbit_handlers(cls):
    for method_name, __ in inspect.getmembers(cls, is_dark_rabbit_handler):
        handler_name = getattr(cls, method_name).__dark_rabbit_handler_name__
        yield method_name, handler_name
