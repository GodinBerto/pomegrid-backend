from functools import wraps

from flask import jsonify, request
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request

from extensions.redis_client import get_redis_client
from routes import response


def _request_identifier():
    user_key = None
    try:
        verify_jwt_in_request(optional=True)
        identity = get_jwt_identity()
        if identity is not None:
            user_key = f"user:{identity}"
    except Exception:
        user_key = None

    if user_key:
        return user_key

    forwarded_for = request.headers.get("X-Forwarded-For", "")
    if forwarded_for:
        ip = forwarded_for.split(",")[0].strip()
    else:
        ip = request.remote_addr or "unknown"
    return f"ip:{ip}"


def rate_limit(key_prefix, limit=30, window_seconds=60):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                redis_client = get_redis_client()
                identifier = _request_identifier()
                key = f"ratelimit:{key_prefix}:{identifier}"
                count = redis_client.incr(key)
                if count == 1:
                    redis_client.expire(key, window_seconds)
                if count > limit:
                    return jsonify(response(None, "Too many requests", 429)), 429
            except Exception:
                # Keep API available if Redis is down.
                pass

            return func(*args, **kwargs)

        return wrapper

    return decorator
