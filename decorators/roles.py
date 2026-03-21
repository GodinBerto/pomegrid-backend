from functools import wraps

from middleware.authMiddleware import (
    ROLE_ADMIN,
    ROLE_USER,
    ROLE_WORKER,
    auth_middleware,
    get_authenticated_user_id,
    normalize_role,
)

__all__ = [
    "ROLE_ADMIN",
    "ROLE_USER",
    "ROLE_WORKER",
    "admin_required",
    "get_authenticated_user_id",
    "normalize_role",
    "role_required",
    "user_required",
    "worker_required",
]


def role_required(*allowed_roles):
    allowed = tuple(normalize_role(role) for role in allowed_roles if role is not None)

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            response = auth_middleware(*allowed)
            if response is not None:
                return response
            return func(*args, **kwargs)

        return wrapper

    return decorator


def admin_required(func):
    return role_required(ROLE_ADMIN)(func)


def worker_required(func):
    return role_required(ROLE_WORKER)(func)


def user_required(func):
    return role_required(ROLE_USER, ROLE_WORKER, ROLE_ADMIN)(func)
