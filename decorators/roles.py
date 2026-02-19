from functools import wraps
from flask import jsonify
from flask_jwt_extended import get_jwt_identity, jwt_required
from database import db_connection
from routes import response


def _get_user(user_id):
    conn, cursor = db_connection()
    cursor.execute(
        "SELECT id, is_admin, is_active, user_type FROM Users WHERE id = ?",
        (user_id,),
    )
    user = cursor.fetchone()
    conn.close()
    return user


def admin_required(func):
    @wraps(func)
    @jwt_required()
    def wrapper(*args, **kwargs):
        user_id = get_jwt_identity()
        user = _get_user(user_id)
        if not user:
            return jsonify(response(None, "User not found", 404)), 404
        if not user["is_active"]:
            return jsonify(response(None, "User account is inactive", 403)), 403
        is_admin = bool(user["is_admin"]) or user["user_type"] in {"admin", "super admin"}
        if not is_admin:
            return jsonify(response(None, "Admin access required", 403)), 403
        return func(*args, **kwargs)

    return wrapper
