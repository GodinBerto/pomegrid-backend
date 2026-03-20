import logging

from extensions.redis_client import get_redis_client


logger = logging.getLogger(__name__)

def revoke_token(jti, expires_in):
    if not jti:
        return False

    try:
        ttl_seconds = int(expires_in or 0)
    except (TypeError, ValueError):
        ttl_seconds = 0

    if ttl_seconds <= 0:
        return False

    try:
        redis_client = get_redis_client()
        redis_client.setex(f"revoked:{jti}", ttl_seconds, "true")
        return True
    except Exception as e:
        logger.warning("Redis unavailable, skipping token revoke: %s", e)
        return False

def is_token_revoked(jti):
    if not jti:
        return False

    try:
        redis_client = get_redis_client()
        return redis_client.exists(f"revoked:{jti}") == 1
    except Exception as e:
        logger.warning("Redis unavailable, skipping revocation check: %s", e)
        return False
