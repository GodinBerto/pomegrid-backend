from functools import wraps
from decorators import token_active, token_present, token_valid

def auth_required(check_active=True):
    def decorator(f):
        @wraps(f)
        @token_present
        @token_valid
        @token_active if check_active else f
        def wrapped(*args, **kwargs):
            return f(*args, **kwargs)
        return wrapped
    return decorator
