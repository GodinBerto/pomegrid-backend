import threading
from time import monotonic

import redis
from flask import current_app


_FAILURE_LOCK = threading.Lock()
_UNAVAILABLE_UNTIL = 0.0
_CLIENT_EXTENSION_KEY = "pomegrid.redis_client"
_CLIENT_SETTINGS_EXTENSION_KEY = "pomegrid.redis_settings"


class RedisUnavailableError(RuntimeError):
    """Raised when Redis is disabled or temporarily unavailable."""


def _cooldown_remaining():
    with _FAILURE_LOCK:
        remaining = _UNAVAILABLE_UNTIL - monotonic()
    return max(0.0, remaining)


def _mark_unavailable():
    retry_seconds = float(current_app.config.get("REDIS_UNAVAILABLE_RETRY_SECONDS", 30.0))
    unavailable_until = monotonic() + max(0.0, retry_seconds)
    with _FAILURE_LOCK:
        global _UNAVAILABLE_UNTIL
        _UNAVAILABLE_UNTIL = unavailable_until


def _clear_unavailable():
    with _FAILURE_LOCK:
        global _UNAVAILABLE_UNTIL
        _UNAVAILABLE_UNTIL = 0.0


def _ensure_available():
    remaining = _cooldown_remaining()
    if remaining > 0:
        raise RedisUnavailableError(
            f"Redis unavailable; retrying in {remaining:.1f}s"
        )


def _redis_settings():
    redis_enabled = bool(current_app.config.get("REDIS_ENABLED", True))
    redis_host = str(current_app.config.get("REDIS_HOST", "") or "").strip()
    if not redis_enabled or not redis_host:
        raise RedisUnavailableError("Redis is disabled")

    return {
        "host": redis_host,
        "port": int(current_app.config.get("REDIS_PORT", 6379)),
        "db": int(current_app.config.get("REDIS_DB", 0)),
        "decode_responses": True,
        "socket_connect_timeout": float(
            current_app.config.get("REDIS_SOCKET_CONNECT_TIMEOUT", 0.2)
        ),
        "socket_timeout": float(current_app.config.get("REDIS_SOCKET_TIMEOUT", 0.2)),
        "retry_on_timeout": False,
        "health_check_interval": 0,
    }


def _get_or_create_client():
    settings = _redis_settings()
    extensions = current_app.extensions
    client = extensions.get(_CLIENT_EXTENSION_KEY)
    cached_settings = extensions.get(_CLIENT_SETTINGS_EXTENSION_KEY)

    if client is None or cached_settings != settings:
        client = redis.Redis(**settings)
        extensions[_CLIENT_EXTENSION_KEY] = client
        extensions[_CLIENT_SETTINGS_EXTENSION_KEY] = settings

    return client


class _FailFastRedisProxy:
    def __init__(self, client):
        self._client = client

    def __getattr__(self, name):
        attribute = getattr(self._client, name)
        if not callable(attribute):
            return attribute

        def _wrapped(*args, **kwargs):
            _ensure_available()
            try:
                result = attribute(*args, **kwargs)
            except (redis.exceptions.RedisError, OSError) as exc:
                _mark_unavailable()
                raise RedisUnavailableError(str(exc)) from exc

            _clear_unavailable()
            return result

        return _wrapped


def get_redis_client():
    _ensure_available()
    return _FailFastRedisProxy(_get_or_create_client())
