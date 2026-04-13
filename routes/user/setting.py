import hashlib
import hmac
import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from flask import Blueprint, current_app, jsonify, request, url_for
from werkzeug.utils import secure_filename

from database import db_connection
from decorators.rate_limit import rate_limit
from decorators.roles import ROLE_ADMIN, ROLE_USER, ROLE_WORKER, get_authenticated_user_id
from extensions.redis_client import get_redis_client
from routes.api_envelope import envelope
from routes.middleware import protect_blueprint
from services.passwords import hash_password, verify_password


settings = Blueprint("settings", __name__)
protect_blueprint(settings, ROLE_USER, ROLE_WORKER, ROLE_ADMIN)
logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 60
PROFILE_CACHE_SECTION = "profile"
NOTIFICATIONS_CACHE_SECTION = "notifications"
PAYMENT_METHODS_CACHE_SECTION = "payments:methods"
BILLING_CACHE_SECTION = "payments:billing"
ALLOWED_AVATAR_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
NOTIFICATION_CATEGORY_LABELS = {
    "account": "Account",
    "orders": "Orders",
    "messages": "Messages",
    "marketing": "Marketing",
}
NOTIFICATION_CATEGORY_ORDER = ("account", "orders", "messages", "marketing")
NOTIFICATION_SETTINGS = (
    {
        "id": "security_alerts",
        "category": "account",
        "label": "Security alerts",
        "description": "Receive important security and sign-in notifications.",
        "default_enabled": True,
    },
    {
        "id": "account_updates",
        "category": "account",
        "label": "Account updates",
        "description": "Receive updates about account changes and verification.",
        "default_enabled": True,
    },
    {
        "id": "order_updates",
        "category": "orders",
        "label": "Order updates",
        "description": "Receive updates when your order status changes.",
        "default_enabled": True,
    },
    {
        "id": "payment_updates",
        "category": "orders",
        "label": "Payment updates",
        "description": "Receive payment confirmations and billing notices.",
        "default_enabled": True,
    },
    {
        "id": "support_messages",
        "category": "messages",
        "label": "Support messages",
        "description": "Receive messages from support and service conversations.",
        "default_enabled": True,
    },
    {
        "id": "marketing_emails",
        "category": "marketing",
        "label": "Marketing emails",
        "description": "Receive occasional promotions and feature announcements.",
        "default_enabled": False,
    },
)
NOTIFICATION_SETTING_MAP = {
    setting["id"]: setting for setting in NOTIFICATION_SETTINGS
}


def _current_user_id():
    return get_authenticated_user_id()


def _normalize_text(value):
    return str(value or "").strip()


def _normalize_email(value):
    return _normalize_text(value).lower()


def _normalize_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return None


def _cache_key(section, user_id):
    return f"settings:{section}:{user_id}"


def _cache_get(key):
    try:
        redis_client = get_redis_client()
        cached = redis_client.get(key)
        return json.loads(cached) if cached else None
    except Exception:
        return None


def _cache_set(key, payload, ttl=CACHE_TTL_SECONDS):
    try:
        redis_client = get_redis_client()
        redis_client.setex(key, ttl, json.dumps(payload))
    except Exception:
        pass


def _invalidate_settings_cache(user_id, *sections):
    section_list = sections or (
        PROFILE_CACHE_SECTION,
        NOTIFICATIONS_CACHE_SECTION,
        PAYMENT_METHODS_CACHE_SECTION,
        BILLING_CACHE_SECTION,
    )
    keys = [_cache_key(section, user_id) for section in section_list]
    try:
        redis_client = get_redis_client()
        redis_client.delete(*keys)
    except Exception:
        pass


def _split_full_name(full_name):
    parts = [part for part in _normalize_text(full_name).split(" ") if part]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def _build_full_name(first_name, last_name):
    return " ".join(part for part in (_normalize_text(first_name), _normalize_text(last_name)) if part).strip()


def _serialize_profile_row(row):
    first_name, last_name = _split_full_name(row["full_name"])
    avatar_url = row["avatar"] or row["profile_image_url"]
    return {
        "firstName": first_name,
        "lastName": last_name,
        "email": row["email"],
        "phone": row["phone"],
        "bio": row["bio"],
        "avatarUrl": avatar_url,
    }


def _avatar_upload_dir():
    static_root = Path(current_app.static_folder or (Path(current_app.root_path) / "static"))
    upload_dir = static_root / "uploads" / "avatars"
    upload_dir.mkdir(parents=True, exist_ok=True)
    return upload_dir


def _fetch_profile_payload(cursor, user_id):
    cursor.execute(
        """
        SELECT id, full_name, email, phone, bio, profile_image_url, avatar
        FROM Users
        WHERE id = ?
        """,
        (user_id,),
    )
    row = cursor.fetchone()
    return _serialize_profile_row(row) if row else None


def _notification_payload(cursor, user_id):
    cursor.execute(
        """
        SELECT setting_id, enabled
        FROM user_notification_preferences
        WHERE user_id = ?
        """,
        (user_id,),
    )
    overrides = {
        row["setting_id"]: bool(row["enabled"])
        for row in cursor.fetchall()
    }

    grouped = {category: [] for category in NOTIFICATION_CATEGORY_ORDER}
    for setting in NOTIFICATION_SETTINGS:
        grouped[setting["category"]].append(
            {
                "id": setting["id"],
                "label": setting["label"],
                "description": setting["description"],
                "enabled": overrides.get(setting["id"], bool(setting["default_enabled"])),
                "defaultEnabled": bool(setting["default_enabled"]),
            }
        )

    groups = []
    for category in NOTIFICATION_CATEGORY_ORDER:
        groups.append(
            {
                "id": category,
                "label": NOTIFICATION_CATEGORY_LABELS[category],
                "settings": grouped[category],
            }
        )
    return {"groups": groups}


def _card_number_digits(value):
    return "".join(character for character in str(value or "") if character.isdigit())


def _luhn_check(card_number):
    digits = _card_number_digits(card_number)
    if len(digits) < 12:
        return False

    total = 0
    reverse_digits = digits[::-1]
    for index, digit in enumerate(reverse_digits):
        value = int(digit)
        if index % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def _detect_card_type(card_number):
    digits = _card_number_digits(card_number)
    if digits.startswith("4"):
        return "visa"
    if len(digits) >= 2 and 51 <= int(digits[:2]) <= 55:
        return "mastercard"
    if len(digits) >= 4 and 2221 <= int(digits[:4]) <= 2720:
        return "mastercard"
    if digits.startswith(("34", "37")):
        return "amex"
    if digits.startswith("6011") or digits.startswith("65"):
        return "discover"
    if len(digits) >= 3 and 644 <= int(digits[:3]) <= 649:
        return "discover"
    return "card"


def _parse_expiry(expiry_value):
    normalized = _normalize_text(expiry_value).replace(" ", "")
    parts = normalized.split("/", 1)
    if len(parts) != 2:
        raise ValueError("expiry must be in MM/YY or MM/YYYY format")

    try:
        month = int(parts[0])
        year = int(parts[1])
    except ValueError as exc:
        raise ValueError("expiry must contain a valid month and year") from exc

    if month < 1 or month > 12:
        raise ValueError("expiry month must be between 1 and 12")

    if year < 100:
        year += 2000
    if year < 2000 or year > 9999:
        raise ValueError("expiry year is invalid")

    today = datetime.utcnow()
    if (year, month) < (today.year, today.month):
        raise ValueError("card has expired")

    return month, year


def _payment_token_hash(card_number, expiry_month, expiry_year):
    secret = current_app.config.get("SECRET_KEY") or current_app.config.get("JWT_SECRET_KEY") or "pomegrid"
    token = f"{_card_number_digits(card_number)}|{int(expiry_month):02d}|{int(expiry_year)}"
    return hmac.new(
        str(secret).encode("utf-8"),
        token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _masked_card_number(last4):
    return f"**** **** **** {last4}"


def _serialize_payment_method(row):
    expiry_year = int(row["expiry_year"])
    return {
        "id": int(row["id"]),
        "name": row["name_on_card"],
        "last4": row["last4"],
        "maskedNumber": _masked_card_number(row["last4"]),
        "type": row["card_type"],
        "expiry": f"{int(row['expiry_month']):02d}/{str(expiry_year)[-2:]}",
        "isDefault": bool(row["is_default"]),
    }


def _payment_methods_payload(cursor, user_id):
    cursor.execute(
        """
        SELECT id, name_on_card, last4, card_type, expiry_month, expiry_year, is_default
        FROM user_payment_methods
        WHERE user_id = ?
        ORDER BY is_default DESC, created_at DESC, id DESC
        """,
        (user_id,),
    )
    return [_serialize_payment_method(row) for row in cursor.fetchall()]


def _empty_billing_payload():
    return {
        "street": None,
        "city": None,
        "state": None,
        "zip": None,
        "country": None,
    }


def _billing_payload(cursor, user_id):
    cursor.execute(
        """
        SELECT street, city, state, zip, country
        FROM user_billing_addresses
        WHERE user_id = ?
        """,
        (user_id,),
    )
    row = cursor.fetchone()
    if not row:
        return _empty_billing_payload()
    return {
        "street": row["street"],
        "city": row["city"],
        "state": row["state"],
        "zip": row["zip"],
        "country": row["country"],
    }


MAX_AVATAR_SIZE_BYTES = 2 * 1024 * 1024
SETTINGS_PROFILE_COLUMNS = """
    id, full_name, email, phone, bio, profile_image_url, avatar, password_hash
"""
PAYMENT_METHOD_COLUMNS = """
    id, name_on_card, last4, card_type, expiry_month, expiry_year, is_default
"""


def _cached_settings_payload(section, user_id, builder):
    cache_key = _cache_key(section, user_id)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    conn = None
    try:
        conn, cursor = db_connection()
        payload = builder(cursor, user_id)
        if payload is not None:
            _cache_set(cache_key, payload)
        return payload
    finally:
        if conn is not None:
            conn.close()


def _fetch_user_settings_row(cursor, user_id):
    cursor.execute(
        f"""
        SELECT {SETTINGS_PROFILE_COLUMNS}
        FROM Users
        WHERE id = ?
        """,
        (user_id,),
    )
    return cursor.fetchone()


def _avatar_public_url(filename):
    return url_for(
        "static",
        filename=f"uploads/avatars/{filename}",
        _external=True,
    )


def _payment_method_row(cursor, method_id, user_id):
    cursor.execute(
        f"""
        SELECT {PAYMENT_METHOD_COLUMNS}
        FROM user_payment_methods
        WHERE id = ? AND user_id = ?
        """,
        (method_id, user_id),
    )
    return cursor.fetchone()


@settings.route("", methods=["GET"])
@settings.route("/", methods=["GET"])
def get_settings_overview():
    user_id = _current_user_id()
    if user_id is None:
        return jsonify(envelope(None, "Invalid token identity", 401, False)), 401

    try:
        payload = {
            "profile": _cached_settings_payload(
                PROFILE_CACHE_SECTION, user_id, _fetch_profile_payload
            ),
            "notifications": _cached_settings_payload(
                NOTIFICATIONS_CACHE_SECTION, user_id, _notification_payload
            ),
            "paymentMethods": _cached_settings_payload(
                PAYMENT_METHODS_CACHE_SECTION, user_id, _payment_methods_payload
            ),
            "billing": _cached_settings_payload(
                BILLING_CACHE_SECTION, user_id, _billing_payload
            ),
        }
        return jsonify(envelope(payload, "Settings fetched", 200)), 200
    except Exception as exc:
        logger.exception("Failed to fetch settings overview for user %s", user_id)
        return jsonify(envelope(None, f"Error: {exc}", 500, False)), 500


@settings.route("/profile", methods=["GET"])
def get_settings_profile():
    user_id = _current_user_id()
    if user_id is None:
        return jsonify(envelope(None, "Invalid token identity", 401, False)), 401

    try:
        payload = _cached_settings_payload(
            PROFILE_CACHE_SECTION, user_id, _fetch_profile_payload
        )
        if not payload:
            return jsonify(envelope(None, "Profile not found", 404, False)), 404
        return jsonify(envelope(payload, "Profile fetched", 200)), 200
    except Exception as exc:
        logger.exception("Failed to fetch settings profile for user %s", user_id)
        return jsonify(envelope(None, f"Error: {exc}", 500, False)), 500


@settings.route("/profile", methods=["PATCH"])
@rate_limit("settings-profile-update", limit=30, window_seconds=60)
def update_settings_profile():
    user_id = _current_user_id()
    if user_id is None:
        return jsonify(envelope(None, "Invalid token identity", 401, False)), 401

    data = request.get_json() or {}
    allowed_fields = {"firstName", "lastName", "email", "phone", "bio"}
    provided_fields = allowed_fields.intersection(data.keys())
    if not provided_fields:
        return (
            jsonify(envelope(None, "No profile fields provided", 400, False)),
            400,
        )

    conn = None
    try:
        conn, cursor = db_connection()
        row = _fetch_user_settings_row(cursor, user_id)
        if not row:
            return jsonify(envelope(None, "Profile not found", 404, False)), 404

        current_first_name, current_last_name = _split_full_name(row["full_name"])
        first_name = (
            _normalize_text(data.get("firstName"))
            if "firstName" in data
            else current_first_name
        )
        last_name = (
            _normalize_text(data.get("lastName"))
            if "lastName" in data
            else current_last_name
        )
        email = (
            _normalize_email(data.get("email"))
            if "email" in data
            else _normalize_email(row["email"])
        )
        phone = (
            _normalize_text(data.get("phone"))
            if "phone" in data
            else _normalize_text(row["phone"])
        )
        bio = row["bio"]
        if "bio" in data:
            bio = _normalize_text(data.get("bio")) or None

        full_name = _build_full_name(first_name, last_name)
        if not full_name:
            return jsonify(envelope(None, "Full name is required", 400, False)), 400
        if not email or "@" not in email:
            return jsonify(envelope(None, "A valid email is required", 400, False)), 400
        if not phone:
            return jsonify(envelope(None, "Phone number is required", 400, False)), 400

        cursor.execute(
            """
            SELECT id
            FROM Users
            WHERE LOWER(email) = ? AND id != ?
            LIMIT 1
            """,
            (email, user_id),
        )
        if cursor.fetchone():
            return jsonify(envelope(None, "Email already exists", 409, False)), 409

        cursor.execute(
            """
            UPDATE Users
            SET
                full_name = ?,
                email = ?,
                phone = ?,
                bio = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (full_name, email, phone, bio, user_id),
        )
        conn.commit()

        payload = _fetch_profile_payload(cursor, user_id)
        _invalidate_settings_cache(user_id, PROFILE_CACHE_SECTION)
        if payload is not None:
            _cache_set(_cache_key(PROFILE_CACHE_SECTION, user_id), payload)
        return jsonify(envelope(payload, "Profile updated", 200)), 200
    except sqlite3.IntegrityError as exc:
        if conn is not None:
            conn.rollback()
        logger.exception("Profile update conflict for user %s", user_id)
        return jsonify(envelope(None, f"Error: {exc}", 409, False)), 409
    except Exception as exc:
        if conn is not None:
            conn.rollback()
        logger.exception("Failed to update settings profile for user %s", user_id)
        return jsonify(envelope(None, f"Error: {exc}", 500, False)), 500
    finally:
        if conn is not None:
            conn.close()


@settings.route("/profile/avatar", methods=["POST"])
@rate_limit("settings-avatar-upload", limit=20, window_seconds=60)
def upload_settings_avatar():
    user_id = _current_user_id()
    if user_id is None:
        return jsonify(envelope(None, "Invalid token identity", 401, False)), 401

    avatar_file = request.files.get("avatar")
    if avatar_file is None or not avatar_file.filename:
        return jsonify(envelope(None, "avatar file is required", 400, False)), 400

    original_filename = secure_filename(avatar_file.filename)
    extension = Path(original_filename).suffix.lower()
    if extension not in ALLOWED_AVATAR_EXTENSIONS:
        return (
            jsonify(
                envelope(
                    None,
                    "avatar must be one of .jpg, .jpeg, .png, .webp, .gif",
                    400,
                    False,
                )
            ),
            400,
        )

    file_bytes = avatar_file.read()
    if not file_bytes:
        return jsonify(envelope(None, "avatar file is empty", 400, False)), 400
    if len(file_bytes) > MAX_AVATAR_SIZE_BYTES:
        return jsonify(envelope(None, "avatar must be 2MB or smaller", 400, False)), 400

    filename = f"user-{user_id}-{uuid4().hex}{extension}"
    upload_path = _avatar_upload_dir() / filename
    upload_path.write_bytes(file_bytes)
    avatar_url = _avatar_public_url(filename)

    conn = None
    try:
        conn, cursor = db_connection()
        cursor.execute(
            """
            UPDATE Users
            SET
                avatar = ?,
                profile_image_url = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (avatar_url, avatar_url, user_id),
        )
        conn.commit()

        profile_payload = _fetch_profile_payload(cursor, user_id)
        _invalidate_settings_cache(user_id, PROFILE_CACHE_SECTION)
        if profile_payload is not None:
            _cache_set(_cache_key(PROFILE_CACHE_SECTION, user_id), profile_payload)
        return (
            jsonify(
                envelope(
                    {
                        "avatarUrl": avatar_url,
                        "profile": profile_payload,
                    },
                    "Avatar updated",
                    200,
                )
            ),
            200,
        )
    except Exception as exc:
        if conn is not None:
            conn.rollback()
        logger.exception("Failed to upload avatar for user %s", user_id)
        return jsonify(envelope(None, f"Error: {exc}", 500, False)), 500
    finally:
        if conn is not None:
            conn.close()


@settings.route("/profile/password", methods=["PATCH"])
@rate_limit("settings-password-update", limit=10, window_seconds=300)
def update_settings_password():
    user_id = _current_user_id()
    if user_id is None:
        return jsonify(envelope(None, "Invalid token identity", 401, False)), 401

    data = request.get_json() or {}
    current_password = data.get("currentPassword") or data.get("current_password")
    new_password = data.get("newPassword") or data.get("new_password")
    confirm_password = (
        data.get("confirmPassword")
        or data.get("confirm_password")
        or new_password
    )

    if not current_password or not new_password:
        return (
            jsonify(
                envelope(
                    None,
                    "currentPassword and newPassword are required",
                    400,
                    False,
                )
            ),
            400,
        )
    if len(str(new_password)) < 8:
        return (
            jsonify(
                envelope(
                    None,
                    "New password must be at least 8 characters long",
                    400,
                    False,
                )
            ),
            400,
        )
    if str(new_password) != str(confirm_password):
        return (
            jsonify(envelope(None, "New passwords do not match", 400, False)),
            400,
        )
    if str(current_password) == str(new_password):
        return (
            jsonify(
                envelope(
                    None,
                    "New password must be different from the current password",
                    400,
                    False,
                )
            ),
            400,
        )

    conn = None
    try:
        conn, cursor = db_connection()
        row = _fetch_user_settings_row(cursor, user_id)
        if not row:
            return jsonify(envelope(None, "Profile not found", 404, False)), 404

        if not verify_password(row["password_hash"], current_password):
            return (
                jsonify(envelope(None, "Current password is incorrect", 400, False)),
                400,
            )

        cursor.execute(
            """
            UPDATE Users
            SET password_hash = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (hash_password(new_password), user_id),
        )
        conn.commit()
        return jsonify(envelope({}, "Password updated", 200)), 200
    except Exception as exc:
        if conn is not None:
            conn.rollback()
        logger.exception("Failed to update password for user %s", user_id)
        return jsonify(envelope(None, f"Error: {exc}", 500, False)), 500
    finally:
        if conn is not None:
            conn.close()


@settings.route("/notifications", methods=["GET"])
def get_settings_notifications():
    user_id = _current_user_id()
    if user_id is None:
        return jsonify(envelope(None, "Invalid token identity", 401, False)), 401

    try:
        payload = _cached_settings_payload(
            NOTIFICATIONS_CACHE_SECTION, user_id, _notification_payload
        )
        return jsonify(envelope(payload, "Notification preferences fetched", 200)), 200
    except Exception as exc:
        logger.exception("Failed to fetch notifications settings for user %s", user_id)
        return jsonify(envelope(None, f"Error: {exc}", 500, False)), 500


@settings.route("/notifications", methods=["PATCH"])
@rate_limit("settings-notifications-update", limit=30, window_seconds=60)
def update_settings_notifications():
    user_id = _current_user_id()
    if user_id is None:
        return jsonify(envelope(None, "Invalid token identity", 401, False)), 401

    data = request.get_json() or {}
    raw_updates = data.get("settings") if isinstance(data.get("settings"), dict) else data
    if not isinstance(raw_updates, dict) or not raw_updates:
        return (
            jsonify(
                envelope(None, "At least one notification setting is required", 400, False)
            ),
            400,
        )

    normalized_updates = {}
    for setting_id, value in raw_updates.items():
        if setting_id not in NOTIFICATION_SETTING_MAP:
            return (
                jsonify(
                    envelope(
                        None,
                        f"Unknown notification setting: {setting_id}",
                        400,
                        False,
                    )
                ),
                400,
            )
        normalized_value = _normalize_bool(value)
        if normalized_value is None:
            return (
                jsonify(
                    envelope(
                        None,
                        f"Notification setting {setting_id} must be true or false",
                        400,
                        False,
                    )
                ),
                400,
            )
        normalized_updates[setting_id] = normalized_value

    conn = None
    try:
        conn, cursor = db_connection()
        for setting_id, enabled in normalized_updates.items():
            default_enabled = bool(
                NOTIFICATION_SETTING_MAP[setting_id]["default_enabled"]
            )
            if enabled == default_enabled:
                cursor.execute(
                    """
                    DELETE FROM user_notification_preferences
                    WHERE user_id = ? AND setting_id = ?
                    """,
                    (user_id, setting_id),
                )
                continue

            cursor.execute(
                """
                INSERT INTO user_notification_preferences (
                    user_id,
                    setting_id,
                    enabled,
                    updated_at
                )
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id, setting_id) DO UPDATE SET
                    enabled = excluded.enabled,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (user_id, setting_id, 1 if enabled else 0),
            )

        conn.commit()
        payload = _notification_payload(cursor, user_id)
        _invalidate_settings_cache(user_id, NOTIFICATIONS_CACHE_SECTION)
        _cache_set(_cache_key(NOTIFICATIONS_CACHE_SECTION, user_id), payload)
        return (
            jsonify(envelope(payload, "Notification preferences updated", 200)),
            200,
        )
    except Exception as exc:
        if conn is not None:
            conn.rollback()
        logger.exception("Failed to update notifications settings for user %s", user_id)
        return jsonify(envelope(None, f"Error: {exc}", 500, False)), 500
    finally:
        if conn is not None:
            conn.close()


@settings.route("/notifications/reset", methods=["POST"])
@rate_limit("settings-notifications-reset", limit=10, window_seconds=60)
def reset_settings_notifications():
    user_id = _current_user_id()
    if user_id is None:
        return jsonify(envelope(None, "Invalid token identity", 401, False)), 401

    conn = None
    try:
        conn, cursor = db_connection()
        cursor.execute(
            "DELETE FROM user_notification_preferences WHERE user_id = ?",
            (user_id,),
        )
        conn.commit()

        payload = _notification_payload(cursor, user_id)
        _invalidate_settings_cache(user_id, NOTIFICATIONS_CACHE_SECTION)
        _cache_set(_cache_key(NOTIFICATIONS_CACHE_SECTION, user_id), payload)
        return (
            jsonify(envelope(payload, "Notification preferences reset", 200)),
            200,
        )
    except Exception as exc:
        if conn is not None:
            conn.rollback()
        logger.exception("Failed to reset notifications settings for user %s", user_id)
        return jsonify(envelope(None, f"Error: {exc}", 500, False)), 500
    finally:
        if conn is not None:
            conn.close()


@settings.route("/payments/methods", methods=["GET"])
def get_settings_payment_methods():
    user_id = _current_user_id()
    if user_id is None:
        return jsonify(envelope(None, "Invalid token identity", 401, False)), 401

    try:
        payload = _cached_settings_payload(
            PAYMENT_METHODS_CACHE_SECTION,
            user_id,
            _payment_methods_payload,
        )
        return jsonify(envelope(payload, "Payment methods fetched", 200)), 200
    except Exception as exc:
        logger.exception("Failed to fetch payment methods for user %s", user_id)
        return jsonify(envelope(None, f"Error: {exc}", 500, False)), 500


@settings.route("/payments/methods", methods=["POST"])
@rate_limit("settings-payment-methods-create", limit=15, window_seconds=300)
def create_settings_payment_method():
    user_id = _current_user_id()
    if user_id is None:
        return jsonify(envelope(None, "Invalid token identity", 401, False)), 401

    data = request.get_json() or {}
    name = _normalize_text(
        data.get("name") or data.get("nameOnCard") or data.get("cardholderName")
    )
    card_number = data.get("number") or data.get("cardNumber")
    expiry = data.get("expiry")
    cvc = _normalize_text(data.get("cvc") or data.get("cvv"))
    requested_default = _normalize_bool(
        data.get("isDefault") if "isDefault" in data else data.get("is_default")
    )

    if not name or not card_number or not expiry or not cvc:
        return (
            jsonify(
                envelope(
                    None,
                    "name, number, expiry and cvc are required",
                    400,
                    False,
                )
            ),
            400,
        )
    if not cvc.isdigit() or len(cvc) not in {3, 4}:
        return jsonify(envelope(None, "cvc must be 3 or 4 digits", 400, False)), 400

    digits = _card_number_digits(card_number)
    if len(digits) < 12 or len(digits) > 19 or not _luhn_check(digits):
        return jsonify(envelope(None, "Card number is invalid", 400, False)), 400

    try:
        expiry_month, expiry_year = _parse_expiry(expiry)
    except ValueError as exc:
        return jsonify(envelope(None, str(exc), 400, False)), 400

    token_hash = _payment_token_hash(digits, expiry_month, expiry_year)
    last4 = digits[-4:]
    card_type = _detect_card_type(digits)

    conn = None
    try:
        conn, cursor = db_connection()
        cursor.execute(
            "SELECT COUNT(*) AS total FROM user_payment_methods WHERE user_id = ?",
            (user_id,),
        )
        existing_count = int(cursor.fetchone()["total"] or 0)
        is_default = requested_default is True or existing_count == 0

        if is_default:
            cursor.execute(
                """
                UPDATE user_payment_methods
                SET is_default = 0, updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ?
                """,
                (user_id,),
            )

        cursor.execute(
            """
            INSERT INTO user_payment_methods (
                user_id,
                name_on_card,
                last4,
                card_type,
                expiry_month,
                expiry_year,
                token_hash,
                is_default,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                user_id,
                name,
                last4,
                card_type,
                expiry_month,
                expiry_year,
                token_hash,
                1 if is_default else 0,
            ),
        )
        method_id = cursor.lastrowid
        conn.commit()

        row = _payment_method_row(cursor, method_id, user_id)
        payload = _serialize_payment_method(row) if row else None
        _invalidate_settings_cache(user_id, PAYMENT_METHODS_CACHE_SECTION)
        _cache_set(
            _cache_key(PAYMENT_METHODS_CACHE_SECTION, user_id),
            _payment_methods_payload(cursor, user_id),
        )
        return jsonify(envelope(payload, "Payment method added", 201)), 201
    except sqlite3.IntegrityError:
        if conn is not None:
            conn.rollback()
        return jsonify(envelope(None, "This card is already saved", 409, False)), 409
    except Exception as exc:
        if conn is not None:
            conn.rollback()
        logger.exception("Failed to add payment method for user %s", user_id)
        return jsonify(envelope(None, f"Error: {exc}", 500, False)), 500
    finally:
        if conn is not None:
            conn.close()


@settings.route("/payments/methods/<int:method_id>", methods=["PATCH"])
@rate_limit("settings-payment-methods-update", limit=30, window_seconds=60)
def update_settings_payment_method(method_id):
    user_id = _current_user_id()
    if user_id is None:
        return jsonify(envelope(None, "Invalid token identity", 401, False)), 401

    data = request.get_json() or {}
    set_default = _normalize_bool(
        data.get("isDefault") if "isDefault" in data else data.get("is_default")
    )
    if set_default is not True:
        return (
            jsonify(
                envelope(
                    None,
                    "Only isDefault=true updates are supported",
                    400,
                    False,
                )
            ),
            400,
        )

    conn = None
    try:
        conn, cursor = db_connection()
        existing = _payment_method_row(cursor, method_id, user_id)
        if not existing:
            return jsonify(envelope(None, "Payment method not found", 404, False)), 404

        cursor.execute(
            """
            UPDATE user_payment_methods
            SET is_default = 0, updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ?
            """,
            (user_id,),
        )
        cursor.execute(
            """
            UPDATE user_payment_methods
            SET is_default = 1, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND user_id = ?
            """,
            (method_id, user_id),
        )
        conn.commit()

        row = _payment_method_row(cursor, method_id, user_id)
        payload = _serialize_payment_method(row) if row else None
        _invalidate_settings_cache(user_id, PAYMENT_METHODS_CACHE_SECTION)
        _cache_set(
            _cache_key(PAYMENT_METHODS_CACHE_SECTION, user_id),
            _payment_methods_payload(cursor, user_id),
        )
        return jsonify(envelope(payload, "Payment method updated", 200)), 200
    except Exception as exc:
        if conn is not None:
            conn.rollback()
        logger.exception("Failed to update payment method %s for user %s", method_id, user_id)
        return jsonify(envelope(None, f"Error: {exc}", 500, False)), 500
    finally:
        if conn is not None:
            conn.close()


@settings.route("/payments/methods/<int:method_id>", methods=["DELETE"])
@rate_limit("settings-payment-methods-delete", limit=30, window_seconds=60)
def delete_settings_payment_method(method_id):
    user_id = _current_user_id()
    if user_id is None:
        return jsonify(envelope(None, "Invalid token identity", 401, False)), 401

    conn = None
    try:
        conn, cursor = db_connection()
        existing = _payment_method_row(cursor, method_id, user_id)
        if not existing:
            return jsonify(envelope(None, "Payment method not found", 404, False)), 404

        was_default = bool(existing["is_default"])
        cursor.execute(
            """
            DELETE FROM user_payment_methods
            WHERE id = ? AND user_id = ?
            """,
            (method_id, user_id),
        )

        if was_default:
            cursor.execute(
                """
                SELECT id
                FROM user_payment_methods
                WHERE user_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                (user_id,),
            )
            replacement = cursor.fetchone()
            if replacement:
                cursor.execute(
                    """
                    UPDATE user_payment_methods
                    SET is_default = 1, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (replacement["id"],),
                )

        conn.commit()
        _invalidate_settings_cache(user_id, PAYMENT_METHODS_CACHE_SECTION)
        _cache_set(
            _cache_key(PAYMENT_METHODS_CACHE_SECTION, user_id),
            _payment_methods_payload(cursor, user_id),
        )
        return jsonify(envelope({"id": method_id}, "Payment method removed", 200)), 200
    except Exception as exc:
        if conn is not None:
            conn.rollback()
        logger.exception("Failed to delete payment method %s for user %s", method_id, user_id)
        return jsonify(envelope(None, f"Error: {exc}", 500, False)), 500
    finally:
        if conn is not None:
            conn.close()


@settings.route("/payments/billing", methods=["GET"])
def get_settings_billing_address():
    user_id = _current_user_id()
    if user_id is None:
        return jsonify(envelope(None, "Invalid token identity", 401, False)), 401

    try:
        payload = _cached_settings_payload(
            BILLING_CACHE_SECTION, user_id, _billing_payload
        )
        return jsonify(envelope(payload, "Billing address fetched", 200)), 200
    except Exception as exc:
        logger.exception("Failed to fetch billing settings for user %s", user_id)
        return jsonify(envelope(None, f"Error: {exc}", 500, False)), 500


@settings.route("/payments/billing", methods=["PUT", "PATCH"])
@rate_limit("settings-billing-update", limit=30, window_seconds=60)
def upsert_settings_billing_address():
    user_id = _current_user_id()
    if user_id is None:
        return jsonify(envelope(None, "Invalid token identity", 401, False)), 401

    data = request.get_json() or {}
    billing_fields = ("street", "city", "state", "zip", "country")
    provided_fields = [field for field in billing_fields if field in data]
    if not provided_fields:
        return (
            jsonify(envelope(None, "No billing fields provided", 400, False)),
            400,
        )

    conn = None
    try:
        conn, cursor = db_connection()
        payload = _billing_payload(cursor, user_id)
        for field in provided_fields:
            payload[field] = _normalize_text(data.get(field)) or None

        cursor.execute(
            """
            INSERT INTO user_billing_addresses (
                user_id,
                street,
                city,
                state,
                zip,
                country,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id) DO UPDATE SET
                street = excluded.street,
                city = excluded.city,
                state = excluded.state,
                zip = excluded.zip,
                country = excluded.country,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                user_id,
                payload["street"],
                payload["city"],
                payload["state"],
                payload["zip"],
                payload["country"],
            ),
        )
        conn.commit()

        payload = _billing_payload(cursor, user_id)
        _invalidate_settings_cache(user_id, BILLING_CACHE_SECTION)
        _cache_set(_cache_key(BILLING_CACHE_SECTION, user_id), payload)
        return jsonify(envelope(payload, "Billing address updated", 200)), 200
    except Exception as exc:
        if conn is not None:
            conn.rollback()
        logger.exception("Failed to update billing settings for user %s", user_id)
        return jsonify(envelope(None, f"Error: {exc}", 500, False)), 500
    finally:
        if conn is not None:
            conn.close()
