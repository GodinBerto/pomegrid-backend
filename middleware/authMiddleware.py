from flask import request, jsonify, g
import jwt
import os

SECRET_KEY = os.getenv("JWT_SECRET", "super-secret")

def auth_middleware():
    auth_header = request.headers.get("Authorization")

    if not auth_header or not auth_header.startswith("Bearer "):
        return jsonify({"message": "Unauthorized"}), 401

    token = auth_header.split(" ")[1]

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        g.user_id = payload["user_id"]
        g.jti = payload["jti"]
    except jwt.ExpiredSignatureError:
        return jsonify({"message": "Access token expired"}), 401
    except jwt.InvalidTokenError:
        return jsonify({"message": "Invalid token"}), 401
