from extensions.redis_client import get_redis_client
from flask_jwt_extended import get_jwt

def revoke_token(jti, expires_in):
    redis_client = get_redis_client()
    redis_client.setex(f"revoked:{jti}", expires_in, "true")

def is_token_revoked(jti):
    try:
        redis_client = get_redis_client()
        return redis_client.exists(f"revoked:{jti}") == 1
    except Exception as e:
        # 🔥 Redis down → treat token as NOT revoked
        print("⚠️ Redis unavailable, skipping revocation check:", e)
        return False
