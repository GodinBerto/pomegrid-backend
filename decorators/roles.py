from functools import wraps

from flask import g, jsonify
from flask_jwt_extended import get_jwt_identity, jwt_required

from database import db_connection
from routes.api_envelope import envelope


ROLE_USER = "user"
ROLE_WORKER = "worker"
ROLE_ADMIN = "admin"


def normalize_role(user_type, is_admin=False):
    normalized = (str(user_type or "").strip().lower())
    if normalized in {"admin", "super admin"} or bool(is_admin):
        return ROLE_ADMIN
    if normalized == "worker":
        return ROLE_WORKER
    return ROLE_USER


def _get_user(user_id):
    conn, cursor = db_connection()
    cursor.execute(
        """
        SELECT id, email, full_name, user_type, role, is_admin, is_active, status
        FROM Users
        WHERE id = ?
        """,
        (user_id,),
    )
    user = cursor.fetchone()
    conn.close()
    return user


def role_required(*allowed_roles):
    allowed = {normalize_role(role) for role in allowed_roles}

    def decorator(func):
        @wraps(func)
        @jwt_required()
        def wrapper(*args, **kwargs):
            user_id = int(get_jwt_identity())
            user = _get_user(user_id)
            if not user:
                return jsonify(envelope(None, "User not found", 404, False)), 404
            user_status = str(user["status"] or "").strip().lower()
            is_active = bool(user["is_active"]) and (user_status in {"", "active"})
            if not is_active:
                return jsonify(envelope(None, "User account is inactive", 403, False)), 403

            user_role = normalize_role(user["role"] or user["user_type"], user["is_admin"])
            if user_role not in allowed:
                return jsonify(envelope(None, "Forbidden", 403, False)), 403

            g.current_user = {
                "id": int(user["id"]),
                "email": user["email"],
                "full_name": user["full_name"],
                "user_type": user_role,
                "role": user_role,
                "is_admin": int(bool(user["is_admin"]))
            }
            return func(*args, **kwargs)

        return wrapper

    return decorator


def admin_required(func):
    return role_required(ROLE_ADMIN)(func)


def worker_required(func):
    return role_required(ROLE_WORKER)(func)


def user_required(func):
    return role_required(ROLE_USER, ROLE_WORKER, ROLE_ADMIN)(func)
