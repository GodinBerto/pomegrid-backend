import logging

from flask import Blueprint, jsonify, request
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    get_csrf_token,
    get_jwt,
    get_jwt_identity,
    jwt_required,
    set_refresh_cookies,
    unset_jwt_cookies,
)
from werkzeug.security import check_password_hash, generate_password_hash

from config import Config
from database import db_connection
from decorators.rate_limit import rate_limit
from decorators.roles import normalize_role
from extensions.redis_client import get_redis_client
from routes.api_envelope import envelope
from routes import response
from services.token_service import revoke_token


# Initialize the Flask auth
auth = Blueprint("auth", __name__)
logger = logging.getLogger(__name__)

ALLOWED_USER_TYPES = {"user", "worker", "admin"}
PUBLIC_REGISTRATION_USER_TYPES = {"user", "worker"}


def normalize_user_type(value, default_value="user"):
    if value is None:
        return default_value

    normalized = str(value).strip().lower()
    aliases = {
        "consumer": "user",
        "normal-consumer-user": "user",
        "normal_consumer_user": "user",
        "normal consumer user": "user",
        "farmer": "user",
        "superadmin": "admin",
        "super admin": "admin",
    }
    normalized = aliases.get(normalized, normalized)
    return normalized


@auth.route("/register", methods=["POST"])
@rate_limit("auth-register", limit=20, window_seconds=60)
def register():
    data = request.get_json() or {}
    username = data.get("username")
    password = data.get("password")
    email = data.get("email")
    full_name = data.get("full_name")
    phone = data.get("phone")
    user_type = normalize_user_type(data.get("user_type", "user"))
    address = data.get("address")
    profile_image_url = data.get("profile_image_url")
    date_of_birth = data.get("date_of_birth")

    if not all([username, password, email, full_name, phone, user_type, date_of_birth]):
        return jsonify({"message": "All required fields must be provided"}), 400

    if user_type not in ALLOWED_USER_TYPES:
        return jsonify({"message": "Invalid user_type."}), 400
    if user_type not in PUBLIC_REGISTRATION_USER_TYPES:
        return jsonify({"message": "Only user or worker can self-register."}), 403

    conn, cursor = db_connection()
    cursor.execute("SELECT id FROM Users WHERE username = ? OR email = ?", (username, email))
    existing_user = cursor.fetchone()
    conn.close()
    if existing_user:
        return jsonify({"message": "Username or email already exists"}), 409

    hashed_password = generate_password_hash(password)

    try:
        conn, cursor = db_connection()
        cursor.execute(
            """
            INSERT INTO Users (
                username, email, password_hash, full_name, phone,
                user_type, address, profile_image_url, date_of_birth, avatar
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                username,
                email,
                hashed_password,
                full_name,
                phone,
                user_type,
                address,
                profile_image_url,
                date_of_birth,
                profile_image_url,
            ),
        )

        conn.commit()
        conn.close()

        return jsonify(response([], "User registered successfully", 200)), 201

    except Exception:
        logger.exception("Registration error")
        return jsonify({"message": "Internal server error"}), 500


@auth.route("/register-admin", methods=["POST"])
@rate_limit("auth-register-admin", limit=10, window_seconds=60)
def register_admin():
    data = request.get_json() or {}
    admin_setup_key = data.get("admin_setup_key")
    if admin_setup_key != Config.ADMIN_SETUP_KEY:
        return jsonify(response(None, "Invalid admin setup key", 403)), 403

    username = data.get("username")
    password = data.get("password")
    email = data.get("email")
    full_name = data.get("full_name")
    phone = data.get("phone")
    date_of_birth = data.get("date_of_birth")
    address = data.get("address")
    profile_image_url = data.get("profile_image_url")
    user_type = normalize_user_type(data.get("user_type", "admin"), "admin")

    if not all([username, password, email, full_name, phone, date_of_birth]):
        return jsonify(response(None, "All required fields must be provided", 400)), 400
    if user_type != "admin":
        return jsonify(response(None, 'user_type must be "admin"', 400)), 400

    hashed_password = generate_password_hash(password)
    try:
        conn, cursor = db_connection()
        cursor.execute(
            """
            INSERT INTO Users (
                username, email, password_hash, full_name, phone,
                user_type, address, profile_image_url, date_of_birth, is_admin, avatar
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                username,
                email,
                hashed_password,
                full_name,
                phone,
                user_type,
                address,
                profile_image_url,
                date_of_birth,
                1,
                profile_image_url,
            ),
        )
        user_id = cursor.lastrowid
        cursor.execute("INSERT OR IGNORE INTO Admins (user_id) VALUES (?)", (user_id,))
        conn.commit()
        conn.close()
        return jsonify(response({"user_id": user_id}, "Admin registered successfully", 201)), 201
    except Exception:
        logger.exception("Admin registration error")
        return jsonify({"message": "Internal server error"}), 500


@auth.route("/login", methods=["POST"])
@rate_limit("auth-login", limit=15, window_seconds=60)
def login():
    data = request.get_json() or {}
    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return jsonify(envelope(None, "email and password are required", 400, False)), 400

    conn, cursor = db_connection()
    cursor.execute(
        """
        SELECT id, username, password_hash, email, full_name, phone, user_type,
               role, status, address, is_admin, is_active, date_of_birth
        FROM Users
        WHERE email = ?
        """,
        (email,),
    )
    user = cursor.fetchone()
    conn.close()

    if user is None:
        return jsonify(envelope(None, "Invalid credentials", 401, False)), 401

    (
        user_id,
        username,
        password_hash,
        email,
        full_name,
        phone,
        user_type,
        role,
        status,
        address,
        is_admin,
        is_active,
        date_of_birth,
    ) = user

    if not check_password_hash(password_hash, password):
        return jsonify(envelope(None, "Invalid credentials", 401, False)), 401
    if not bool(is_active):
        return jsonify(envelope(None, "User account is inactive", 403, False)), 403

    normalized_role = normalize_role(role or user_type, is_admin)
    user_status = str(status or ("active" if bool(is_active) else "inactive")).strip().lower()
    user_data = {
        "id": user_id,
        "username": username,
        "email": email,
        "full_name": full_name,
        "phone": phone,
        "role": normalized_role,
        "user_type": normalized_role,
        "status": user_status,
        "address": address,
        "is_admin": int(bool(is_admin) or normalized_role == "admin"),
        "is_active": bool(is_active),
        "date_of_birth": date_of_birth,
    }

    access_token = create_access_token(identity=str(user_id))
    refresh_token = create_refresh_token(identity=str(user_id))

    payload = {
        "access_token": access_token,
        "csrf_token": get_csrf_token(refresh_token),
        "user": user_data,
    }

    resp = jsonify(envelope(payload, "Login successful", 200))
    set_refresh_cookies(resp, refresh_token)

    return resp, 200


@auth.route("/logout", methods=["POST"])
@jwt_required()
@rate_limit("auth-logout", limit=30, window_seconds=60)
def logout():
    jti = get_jwt()["jti"]
    expires = get_jwt()["exp"] - get_jwt()["iat"]

    revoke_token(jti, expires)

    resp = jsonify({"message": "Logged out"})
    unset_jwt_cookies(resp)

    return resp, 200


@auth.route("/refresh", methods=["POST"])
@jwt_required(refresh=True)
@rate_limit("auth-refresh", limit=30, window_seconds=60)
def refresh():
    jwt_data = get_jwt()
    user_id = get_jwt_identity()
    refresh_jti = jwt_data.get("jti")
    expires_in = jwt_data.get("exp", 0) - jwt_data.get("iat", 0)

    refresh_reused = False
    try:
        redis_client = get_redis_client()
        used_key = f"refresh_used:{refresh_jti}"
        refresh_reused = redis_client.exists(used_key) == 1
        if not refresh_reused and expires_in > 0:
            redis_client.setex(used_key, expires_in, "true")
    except Exception as e:
        logger.warning("Redis unavailable, skipping refresh reuse check: %s", e)

    new_access = create_access_token(identity=user_id)
    new_refresh = create_refresh_token(identity=user_id)
    new_csrf = get_csrf_token(new_refresh)

    payload = {
        "access_token": new_access,
        "csrf_token": new_csrf,
    }
    if refresh_reused:
        payload["message"] = "Refresh token already used. We rotated your refresh token; please retry with the new CSRF token."
        payload["requires_retry"] = True

    resp = jsonify(envelope(payload, "Token refreshed", 200))
    set_refresh_cookies(resp, new_refresh)

    return resp, 200


@auth.route("/me", methods=["GET"])
@jwt_required()
def auth_me():
    user_id = get_jwt_identity()
    conn, cursor = db_connection()
    cursor.execute(
        """
        SELECT id, email, full_name, user_type, is_admin
        FROM Users
        WHERE id = ?
        """,
        (user_id,),
    )
    row = cursor.fetchone()
    conn.close()

    if not row:
        return jsonify({"data": None}), 404

    user_type = normalize_role(row["user_type"], row["is_admin"])
    payload = {
        "id": row["id"],
        "email": row["email"],
        "full_name": row["full_name"],
        "user_type": user_type,
        "is_admin": int(bool(row["is_admin"]) or user_type == "admin"),
    }
    return jsonify({"data": payload}), 200


@auth.route("/protected", methods=["GET"])
@jwt_required()
def protected():
    current_user = get_jwt_identity()
    return jsonify({"message": f"Hello, {current_user}! This is a protected route."}), 200
