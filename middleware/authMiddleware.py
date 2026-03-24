from flask import g, jsonify
from flask_jwt_extended import get_jwt, get_jwt_identity, verify_jwt_in_request

from database import db_connection
from routes.api_envelope import envelope


ROLE_USER = "user"
ROLE_WORKER = "worker"
ROLE_ADMIN = "admin"
INVALID_JWT_IDENTITIES = {"", "none", "null", "undefined"}


def normalize_role(user_type, is_admin=False):
    normalized = str(user_type or "").strip().lower()
    if normalized in {"admin", "super admin"} or bool(is_admin):
        return ROLE_ADMIN
    if normalized == "worker":
        return ROLE_WORKER
    return ROLE_USER


def _normalize_identity(raw_identity):
    if raw_identity is None:
        return None

    normalized = str(raw_identity).strip()
    if normalized.lower() in INVALID_JWT_IDENTITIES:
        return None

    try:
        return int(normalized)
    except (TypeError, ValueError):
        return None


def get_authenticated_user_id():
    return _normalize_identity(get_jwt_identity())


def _get_user(user_id):
    conn, cursor = db_connection()
    try:
        cursor.execute(
            """
            SELECT id, email, full_name, user_type, role, is_admin, is_active, status,
                   is_verified, accepted_policy
            FROM Users
            WHERE id = ?
            """,
            (user_id,),
        )
        return cursor.fetchone()
    finally:
        conn.close()


def _is_active_user(user):
    user_status = str(user["status"] or "").strip().lower()
    return bool(user["is_active"]) and user_status in {"", "active"}


def _build_current_user(user):
    user_role = normalize_role(user["role"] or user["user_type"], user["is_admin"])
    return {
        "id": int(user["id"]),
        "email": user["email"],
        "full_name": user["full_name"],
        "user_type": user_role,
        "role": user_role,
        "is_admin": int(bool(user["is_admin"]) or user_role == ROLE_ADMIN),
        "is_active": bool(user["is_active"]),
        "status": str(user["status"] or "").strip().lower() or "active",
        "is_verified": bool(user["is_verified"]),
        "accepted_policy": bool(user["accepted_policy"]),
    }


def load_authenticated_user(*allowed_roles, require_active=True):
    verify_jwt_in_request()

    user_id = get_authenticated_user_id()
    if user_id is None:
        return jsonify(envelope(None, "Invalid token identity", 401, False)), 401

    user = _get_user(user_id)
    if not user:
        return jsonify(envelope(None, "User not found", 404, False)), 404

    if require_active and not _is_active_user(user):
        return jsonify(envelope(None, "User account is inactive", 403, False)), 403
    if require_active and not bool(user["accepted_policy"]):
        return jsonify(envelope(None, "Policy acceptance is required", 403, False)), 403

    current_user = _build_current_user(user)
    allowed = {normalize_role(role) for role in allowed_roles if role is not None}
    if allowed and current_user["role"] not in allowed:
        return jsonify(envelope(None, "Forbidden", 403, False)), 403

    jwt_payload = get_jwt() or {}
    g.current_user = current_user
    g.user_id = current_user["id"]
    g.jti = jwt_payload.get("jti")
    g.jwt_payload = jwt_payload
    return None


def auth_middleware(*allowed_roles, require_active=True):
    return load_authenticated_user(*allowed_roles, require_active=require_active)
