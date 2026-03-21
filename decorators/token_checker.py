from functools import wraps

from middleware.authMiddleware import auth_middleware

def auth_required(check_active=True):
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            response = auth_middleware(require_active=check_active)
            if response is not None:
                return response
            return f(*args, **kwargs)
        return wrapped
    return decorator
