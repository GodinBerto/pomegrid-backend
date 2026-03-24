import logging
from datetime import datetime, timedelta

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
from decorators.roles import get_authenticated_user_id, normalize_role
from extensions.redis_client import get_redis_client
from routes.api_envelope import envelope
from services.verification_service import (
    deliver_verification_code,
    generate_verification_code,
    mask_verification_target,
    validate_verification_target,
)
from services.token_service import revoke_token


# Initialize the Flask auth
auth = Blueprint("auth", __name__)
logger = logging.getLogger(__name__)

ALLOWED_USER_TYPES = {"user", "worker", "admin"}
PUBLIC_REGISTRATION_USER_TYPES = {"user", "worker"}
VERIFICATION_CODE_LENGTH = 6
VERIFICATION_EXPIRY_MINUTES = max(int(Config.VERIFICATION_CODE_EXPIRY_MINUTES or 10), 1)


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


def _normalize_email(value):
    return str(value or "").strip().lower()


def _normalize_text(value):
    return str(value or "").strip()


def _as_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _utc_now():
    return datetime.utcnow()


def _utc_timestamp_in_minutes(minutes):
    return (_utc_now() + timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")


def _parse_db_timestamp(value):
    raw_value = str(value or "").strip()
    if not raw_value:
        return None
    try:
        return datetime.fromisoformat(raw_value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _is_code_match(stored_code, submitted_code):
    normalized_code = _normalize_text(submitted_code)
    stored_value = _normalize_text(stored_code)
    if not stored_value or not normalized_code:
        return False
    if stored_value == normalized_code:
        return True
    try:
        return check_password_hash(stored_value, normalized_code)
    except ValueError:
        return False


def _safe_csrf_token(token):
    try:
        return get_csrf_token(token)
    except Exception:
        return None


def _build_auth_user_payload(row):
    normalized_role = normalize_role(row["role"] or row["user_type"], row["is_admin"])
    user_status = str(
        row["status"] or ("active" if bool(row["is_active"]) else "inactive")
    ).strip().lower()
    return {
        "id": int(row["id"]),
        "username": row["username"],
        "email": row["email"],
        "full_name": row["full_name"],
        "phone": row["phone"],
        "role": normalized_role,
        "user_type": normalized_role,
        "status": user_status,
        "address": row["address"],
        "is_admin": int(bool(row["is_admin"]) or normalized_role == "admin"),
        "is_active": bool(row["is_active"]),
        "is_verified": bool(row["is_verified"]),
        "accepted_policy": bool(row["accepted_policy"]),
        "date_of_birth": row["date_of_birth"],
        "verified_at": row["verified_at"],
    }


def _verification_response_payload(user_id, channel, target, expires_at, delivery_result):
    payload = {
        "user_id": int(user_id),
        "verification_required": True,
        "verification_channel": channel,
        "verification_target": mask_verification_target(channel, target),
        "verification_expires_at": expires_at,
        "delivery_method": delivery_result.get("delivery_method"),
    }
    if delivery_result.get("preview_code"):
        payload["verification_code"] = delivery_result["preview_code"]
    if delivery_result.get("warning"):
        payload["delivery_warning"] = delivery_result["warning"]
    return payload


def _registration_response_payload(user_id, user_type, is_verified, verified_at):
    return {
        "user_id": int(user_id),
        "user_type": normalize_user_type(user_type),
        "is_verified": bool(is_verified),
        "verified_at": verified_at,
        "can_login": True,
    }


def _send_and_store_verification(cursor, user_id, email, phone, verification_channel):
    channel, target = validate_verification_target(verification_channel, email=email, phone=phone)
    verification_code = generate_verification_code(VERIFICATION_CODE_LENGTH)
    verification_hash = generate_password_hash(verification_code)
    expires_at = _utc_timestamp_in_minutes(VERIFICATION_EXPIRY_MINUTES)

    cursor.execute(
        """
        UPDATE Users
        SET verification_code = ?,
            verification_channel = ?,
            verification_target = ?,
            verification_code_expires_at = ?,
            is_verified = 0,
            verified_at = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (verification_hash, channel, target, expires_at, user_id),
    )

    delivery_result = deliver_verification_code(
        channel,
        target,
        verification_code,
        VERIFICATION_EXPIRY_MINUTES,
    )
    return channel, target, expires_at, delivery_result


def _get_user_for_verification(cursor, email=None, username=None, phone=None):
    normalized_email = _normalize_email(email)
    normalized_username = _normalize_text(username)
    normalized_phone = _normalize_text(phone)

    if normalized_email:
        cursor.execute(
            """
            SELECT *
            FROM Users
            WHERE LOWER(email) = ?
            LIMIT 1
            """,
            (normalized_email,),
        )
        return cursor.fetchone()

    if normalized_username:
        cursor.execute(
            """
            SELECT *
            FROM Users
            WHERE username = ?
            LIMIT 1
            """,
            (normalized_username,),
        )
        return cursor.fetchone()

    if normalized_phone:
        cursor.execute(
            """
            SELECT *
            FROM Users
            WHERE phone = ?
            LIMIT 1
            """,
            (normalized_phone,),
        )
        return cursor.fetchone()

    return None


@auth.route("/register", methods=["POST"])
@rate_limit("auth-register", limit=20, window_seconds=60)
def register():
    data = request.get_json() or {}
    username = _normalize_text(data.get("username"))
    password = data.get("password")
    email = _normalize_email(data.get("email"))
    full_name = _normalize_text(data.get("full_name"))
    phone = _normalize_text(data.get("phone"))
    user_type = normalize_user_type(data.get("user_type", "user"))
    address = _normalize_text(data.get("address")) or None
    profile_image_url = _normalize_text(data.get("profile_image_url")) or None
    date_of_birth = _normalize_text(data.get("date_of_birth"))
    accept_policy = _as_bool(data.get("accept_policy") if "accept_policy" in data else data.get("accepted_policy"))

    if not all([username, password, email, full_name, phone, user_type, date_of_birth]):
        return jsonify(envelope(None, "All required fields must be provided", 400, False)), 400
    if not accept_policy:
        return jsonify(envelope(None, "You must accept the policy before registering", 400, False)), 400

    if user_type not in ALLOWED_USER_TYPES:
        return jsonify(envelope(None, "Invalid user_type.", 400, False)), 400
    if user_type not in PUBLIC_REGISTRATION_USER_TYPES:
        return jsonify(envelope(None, "Only user or worker can self-register.", 403, False)), 403

    conn, cursor = db_connection()
    try:
        cursor.execute("SELECT id FROM Users WHERE username = ? OR LOWER(email) = ?", (username, email))
        existing_user = cursor.fetchone()
    finally:
        conn.close()
    if existing_user:
        return jsonify(envelope(None, "Username or email already exists", 409, False)), 409

    hashed_password = generate_password_hash(password)
    is_verified = False
    verified_at = None
    conn = None

    try:
        conn, cursor = db_connection()
        cursor.execute(
            """
            INSERT INTO Users (
                username, email, password_hash, full_name, phone,
                user_type, role, address, profile_image_url, date_of_birth, avatar,
                is_verified, verified_at, accepted_policy, policy_accepted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
            """,
            (
                username,
                email,
                hashed_password,
                full_name,
                phone,
                user_type,
                user_type,
                address,
                profile_image_url,
                date_of_birth,
                profile_image_url,
                0,
                verified_at,
            ),
        )
        user_id = cursor.lastrowid
        conn.commit()
        payload = _registration_response_payload(user_id, user_type, is_verified, verified_at)
        return jsonify(envelope(payload, "User registered. Verification is pending.", 201)), 201

    except Exception:
        if conn:
            conn.rollback()
        logger.exception("Registration error")
        return jsonify(envelope(None, "Internal server error", 500, False)), 500
    finally:
        if conn:
            conn.close()


@auth.route("/register-admin", methods=["POST"])
@rate_limit("auth-register-admin", limit=10, window_seconds=60)
def register_admin():
    data = request.get_json() or {}
    admin_setup_key = data.get("admin_setup_key")
    if admin_setup_key != Config.ADMIN_SETUP_KEY:
        return jsonify(envelope(None, "Invalid admin setup key", 403, False)), 403

    username = _normalize_text(data.get("username"))
    password = data.get("password")
    email = _normalize_email(data.get("email"))
    full_name = _normalize_text(data.get("full_name"))
    phone = _normalize_text(data.get("phone"))
    date_of_birth = _normalize_text(data.get("date_of_birth"))
    address = _normalize_text(data.get("address")) or None
    profile_image_url = _normalize_text(data.get("profile_image_url")) or None
    user_type = normalize_user_type(data.get("user_type", "admin"), "admin")
    accept_policy = _as_bool(
        data.get("accept_policy") if "accept_policy" in data else data.get("accepted_policy"),
        True,
    )

    if not all([username, password, email, full_name, phone, date_of_birth]):
        return jsonify(envelope(None, "All required fields must be provided", 400, False)), 400
    if user_type != "admin":
        return jsonify(envelope(None, 'user_type must be "admin"', 400, False)), 400
    if not accept_policy:
        return jsonify(envelope(None, "You must accept the policy before registering", 400, False)), 400

    hashed_password = generate_password_hash(password)
    verified_at = _utc_now().strftime("%Y-%m-%d %H:%M:%S")
    conn = None
    try:
        conn, cursor = db_connection()
        cursor.execute("SELECT id FROM Users WHERE username = ? OR LOWER(email) = ?", (username, email))
        if cursor.fetchone():
            conn.close()
            return jsonify(envelope(None, "Username or email already exists", 409, False)), 409
        cursor.execute(
            """
            INSERT INTO Users (
                username, email, password_hash, full_name, phone,
                user_type, role, address, profile_image_url, date_of_birth, is_admin, avatar,
                is_verified, verified_at, accepted_policy, policy_accepted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
            """,
            (
                username,
                email,
                hashed_password,
                full_name,
                phone,
                user_type,
                user_type,
                address,
                profile_image_url,
                date_of_birth,
                1,
                profile_image_url,
                1,
                verified_at,
            ),
        )
        user_id = cursor.lastrowid
        cursor.execute("INSERT OR IGNORE INTO Admins (user_id) VALUES (?)", (user_id,))
        conn.commit()
        payload = _registration_response_payload(user_id, user_type, True, verified_at)
        return jsonify(envelope(payload, "Admin registered.", 201)), 201
    except Exception:
        if conn:
            conn.rollback()
        logger.exception("Admin registration error")
        return jsonify(envelope(None, "Internal server error", 500, False)), 500
    finally:
        if conn:
            conn.close()


@auth.route("/verify-registration", methods=["POST"])
@rate_limit("auth-verify-registration", limit=20, window_seconds=60)
def verify_registration():
    data = request.get_json() or {}
    code = _normalize_text(data.get("code"))
    email = _normalize_email(data.get("email"))
    username = _normalize_text(data.get("username"))
    phone = _normalize_text(data.get("phone"))

    if not code:
        return jsonify(envelope(None, "code is required", 400, False)), 400
    if not any([email, username, phone]):
        return jsonify(envelope(None, "email, username, or phone is required", 400, False)), 400

    conn = None
    try:
        conn, cursor = db_connection()
        user = _get_user_for_verification(cursor, email=email, username=username, phone=phone)
        if not user:
            return jsonify(envelope(None, "User not found", 404, False)), 404
        if bool(user["is_verified"]):
            payload = {
                "user_id": int(user["id"]),
                "is_verified": True,
                "verified_at": user["verified_at"],
            }
            return jsonify(envelope(payload, "User is already verified", 200)), 200

        expires_at = _parse_db_timestamp(user["verification_code_expires_at"])
        if expires_at is not None and expires_at < _utc_now():
            return jsonify(
                envelope(
                    None,
                    "Verification code has expired. Please request a new code.",
                    400,
                    False,
                )
            ), 400

        if not _is_code_match(user["verification_code"], code):
            return jsonify(envelope(None, "Invalid verification code", 400, False)), 400

        cursor.execute(
            """
            UPDATE Users
            SET is_verified = 1,
                verified_at = CURRENT_TIMESTAMP,
                verification_code = NULL,
                verification_channel = NULL,
                verification_target = NULL,
                verification_code_expires_at = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (user["id"],),
        )
        conn.commit()
        payload = {
            "user_id": int(user["id"]),
            "is_verified": True,
            "verified_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            "can_login": True,
        }
        return jsonify(envelope(payload, "Verification successful. You can now log in.", 200)), 200
    except Exception:
        if conn:
            conn.rollback()
        logger.exception("Verification confirmation error")
        return jsonify(envelope(None, "Internal server error", 500, False)), 500
    finally:
        if conn:
            conn.close()


@auth.route("/resend-verification-code", methods=["POST"])
@rate_limit("auth-resend-verification", limit=10, window_seconds=60)
def resend_verification_code():
    data = request.get_json() or {}
    email = _normalize_email(data.get("email"))
    username = _normalize_text(data.get("username"))
    phone = _normalize_text(data.get("phone"))
    requested_channel = data.get("verification_channel")

    if not any([email, username, phone]):
        return jsonify(envelope(None, "email, username, or phone is required", 400, False)), 400

    conn = None
    try:
        conn, cursor = db_connection()
        user = _get_user_for_verification(cursor, email=email, username=username, phone=phone)
        if not user:
            return jsonify(envelope(None, "User not found", 404, False)), 404
        if bool(user["is_verified"]):
            return jsonify(envelope(None, "User is already verified", 400, False)), 400

        channel = requested_channel or user["verification_channel"] or "email"
        channel, target, expires_at, delivery_result = _send_and_store_verification(
            cursor,
            user["id"],
            user["email"],
            user["phone"],
            channel,
        )
        conn.commit()
        payload = _verification_response_payload(
            user["id"],
            channel,
            target,
            expires_at,
            delivery_result,
        )
        return jsonify(envelope(payload, "Verification code resent.", 200)), 200
    except RuntimeError as exc:
        if conn:
            conn.rollback()
        logger.exception("Verification resend delivery error")
        return jsonify(envelope(None, f"Unable to send verification code: {exc}", 503, False)), 503
    except ValueError as exc:
        if conn:
            conn.rollback()
        return jsonify(envelope(None, str(exc), 400, False)), 400
    except Exception:
        if conn:
            conn.rollback()
        logger.exception("Verification resend error")
        return jsonify(envelope(None, "Internal server error", 500, False)), 500
    finally:
        if conn:
            conn.close()


@auth.route("/login", methods=["POST"])
@rate_limit("auth-login", limit=15, window_seconds=60)
def login():
    data = request.get_json() or {}
    email = _normalize_email(data.get("email"))
    password = data.get("password")

    if not email or not password:
        return jsonify(envelope(None, "email and password are required", 400, False)), 400

    conn, cursor = db_connection()
    cursor.execute(
        """
        SELECT id, username, password_hash, email, full_name, phone, user_type,
               role, status, address, is_admin, is_active, is_verified,
               accepted_policy, date_of_birth, verified_at, verification_channel,
               verification_target
        FROM Users
        WHERE LOWER(email) = ?
        """,
        (email,),
    )
    user = cursor.fetchone()
    conn.close()

    if user is None:
        return jsonify(envelope(None, "Invalid credentials", 401, False)), 401

    try:
        user_id = int(user["id"])
    except (TypeError, ValueError):
        logger.error("Login failed because user id is invalid for email %s: %r", email, user["id"])
        return jsonify(envelope(None, "Unable to authenticate user", 500, False)), 500

    if not check_password_hash(user["password_hash"], password):
        return jsonify(envelope(None, "Invalid credentials", 401, False)), 401
    if not bool(user["is_active"]):
        return jsonify(envelope(None, "User account is inactive", 403, False)), 403
    if not bool(user["accepted_policy"]):
        return jsonify(
            envelope(
                {
                    "requires_policy_acceptance": True,
                },
                "You must accept the policy before logging in.",
                403,
                False,
            )
        ), 403
    user_data = _build_auth_user_payload(user)

    access_token = create_access_token(identity=str(user_id))
    refresh_token = create_refresh_token(identity=str(user_id))

    payload = {
        "access_token": access_token,
        "user": user_data,
    }
    csrf_token = _safe_csrf_token(refresh_token)
    if csrf_token:
        payload["csrf_token"] = csrf_token

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
    user_id = get_authenticated_user_id()
    if user_id is None:
        resp = jsonify(
            {
                "message": "Invalid refresh token identity. Please sign in again.",
                "requires_login": True,
            }
        )
        unset_jwt_cookies(resp)
        return resp, 401

    conn, cursor = db_connection()
    cursor.execute(
        "SELECT is_active, status, is_verified, accepted_policy FROM Users WHERE id = ?",
        (user_id,),
    )
    user_row = cursor.fetchone()
    conn.close()
    if not user_row:
        resp = jsonify(
            {
                "message": "User account no longer exists. Please sign in again.",
                "requires_login": True,
            }
        )
        unset_jwt_cookies(resp)
        return resp, 401

    user_status = str(
        user_row["status"] or ("active" if bool(user_row["is_active"]) else "inactive")
    ).strip().lower()
    user_is_active = bool(user_row["is_active"]) and user_status in {"", "active"}
    if not user_is_active:
        resp = jsonify(
            {
                "message": "User account is inactive. Please sign in again.",
                "requires_login": True,
            }
        )
        unset_jwt_cookies(resp)
        return resp, 403
    if not bool(user_row["accepted_policy"]):
        resp = jsonify(
            {
                "message": "You must accept the policy before continuing.",
                "requires_login": True,
            }
        )
        unset_jwt_cookies(resp)
        return resp, 403
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

    new_access = create_access_token(identity=str(user_id))
    new_refresh = create_refresh_token(identity=str(user_id))

    payload = {
        "access_token": new_access,
    }
    new_csrf = _safe_csrf_token(new_refresh)
    if new_csrf:
        payload["csrf_token"] = new_csrf
    if refresh_reused:
        payload["message"] = "Refresh token already used. We rotated your refresh token; please retry with the new CSRF token."
        payload["requires_retry"] = True

    resp = jsonify(payload)
    set_refresh_cookies(resp, new_refresh)

    return resp, 200


@auth.route("/me", methods=["GET"])
@jwt_required()
def auth_me():
    user_id = get_authenticated_user_id()
    if user_id is None:
        return jsonify(envelope(None, "Invalid token identity", 401, False)), 401
    conn, cursor = db_connection()
    cursor.execute(
        """
        SELECT id, username, email, full_name, phone, user_type, role, status,
               address, is_admin, is_active, is_verified, accepted_policy,
               date_of_birth, verified_at
        FROM Users
        WHERE id = ?
        """,
        (user_id,),
    )
    row = cursor.fetchone()
    conn.close()

    if not row:
        return jsonify({"data": None}), 404

    payload = _build_auth_user_payload(row)
    return jsonify({"data": payload}), 200


@auth.route("/protected", methods=["GET"])
@jwt_required()
def protected():
    current_user = get_jwt_identity()
    return jsonify({"message": f"Hello, {current_user}! This is a protected route."}), 200
