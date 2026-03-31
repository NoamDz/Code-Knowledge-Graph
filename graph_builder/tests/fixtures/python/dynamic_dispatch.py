import functools


class Router:
    def dispatch(self, action, params):
        handler_method = getattr(self, "handle_get", None)
        if handler_method:
            handler_method(params)

    def dynamic_dispatch(self, method_name, data):
        processor = getattr(self, method_name, self.process_unknown)
        processor(data)

    def set_field(self, name, value):
        setattr(self, name, value)

    def handle_get(self, params):
        pass

    def process_unknown(self, data):
        pass


def timing_decorator(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        import time
        start = time.time()
        result = func(*args, **kwargs)
        elapsed = time.time() - start
        return result
    return wrapper


def retry(max_attempts=3):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for i in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception:
                    if i == max_attempts - 1:
                        raise
        return wrapper
    return decorator
