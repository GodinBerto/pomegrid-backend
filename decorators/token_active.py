from functools import wraps
from flask import jsonify, g

def token_active(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        token_id = g.jwt_payload.get("jti")

        # Example DB check
        if not is_token_active(token_id):
            return jsonify({"message": "Token revoked"}), 401

        g.user_id = g.jwt_payload.get("user_id")
        return f(*args, **kwargs)

    return wrapper


def is_token_active(token_id):
    # DB / Redis / cache lookup
    return True
