from functools import wraps
from flask import request, jsonify, g

def token_present(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get("Authorization")

        if not auth_header:
            return jsonify({"message": "Authorization header missing"}), 401

        if not auth_header.startswith("Bearer "):
            return jsonify({"message": "Invalid authorization format"}), 401

        g.token = auth_header.split(" ")[1]
        return f(*args, **kwargs)

    return wrapper
