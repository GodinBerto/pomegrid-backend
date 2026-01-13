import redis
from flask import current_app

def get_redis_client():
    return redis.Redis(
        host=current_app.config.get("REDIS_HOST", "localhost"),
        port=current_app.config.get("REDIS_PORT", 6379),
        decode_responses=True
    )
