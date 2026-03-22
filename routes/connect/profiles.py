from flask import jsonify, request

from database import db_connection
from routes.api_envelope import envelope

from .common import (
    _current_user_id,
    _normalize_account_type,
    _parse_datetime,
    _safe_text,
    connect_api,
    logger,
)


def _connect_profile_query():
    return """
        SELECT
            u.id,
            u.full_name,
            u.email,
            u.phone,
            u.role,
            u.user_type,
            u.is_admin,
            u.is_verified,
            u.profile_image_url,
            u.avatar,
            u.created_at,
            u.updated_at AS user_updated_at,
            cp.account_type,
            cp.company,
            cp.country,
            cp.bio,
            cp.min_order_qty,
            cp.response_time,
            cp.created_at AS connect_created_at,
            cp.updated_at AS connect_updated_at
        FROM Users u
        LEFT JOIN ConnectProfiles cp ON cp.user_id = u.id
        WHERE u.id = ?
        LIMIT 1
    """


def _fetch_connect_profile_row(cursor, user_id):
    cursor.execute(_connect_profile_query(), (int(user_id),))
    return cursor.fetchone()


def _serialize_connect_profile(row):
    account_type = _normalize_account_type(row["account_type"])
    created_at = row["connect_created_at"] or row["created_at"]
    created_dt = _parse_datetime(created_at)
    return {
        "id": int(row["id"]),
        "name": row["full_name"],
        "full_name": row["full_name"],
        "email": row["email"],
        "phone": row["phone"],
        "role": account_type,
        "account_type": account_type,
        "company": _safe_text(row["company"]),
        "country": _safe_text(row["country"]),
        "bio": _safe_text(row["bio"]),
        "avatar": row["avatar"] or row["profile_image_url"],
        "profile_image_url": row["profile_image_url"] or row["avatar"],
        "is_verified": bool(row["is_verified"]),
        "min_order_qty": _safe_text(row["min_order_qty"]),
        "response_time": _safe_text(row["response_time"]) or "Within 24 hours",
        "established": str(created_dt.year) if created_dt else "",
        "created_at": created_at,
        "updated_at": row["connect_updated_at"] or row["user_updated_at"],
    }


def _require_connect_profile(cursor, user_id):
    row = _fetch_connect_profile_row(cursor, user_id)
    if not row or _normalize_account_type(row["account_type"]) is None:
        return None
    return row


def _upsert_connect_profile(cursor, user_id, payload):
    cursor.execute(
        """
        INSERT INTO ConnectProfiles (
            user_id,
            account_type,
            company,
            country,
            bio,
            min_order_qty,
            response_time
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            account_type = excluded.account_type,
            company = excluded.company,
            country = excluded.country,
            bio = excluded.bio,
            min_order_qty = excluded.min_order_qty,
            response_time = excluded.response_time,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            int(user_id),
            payload["account_type"],
            payload["company"],
            payload["country"],
            payload["bio"],
            payload["min_order_qty"],
            payload["response_time"],
        ),
    )


@connect_api.route("/", methods=["GET"])
def get_connect_profile():
    user_id = _current_user_id()
    try:
        conn, cursor = db_connection()
        row = _require_connect_profile(cursor, user_id)
        conn.close()
        if not row:
            return jsonify(envelope(None, "Connect profile not found", 404, False)), 404
        return jsonify(envelope(_serialize_connect_profile(row), "Connect profile fetched", 200)), 200
    except Exception as e:
        logger.exception("Failed to fetch connect profile for %s", user_id)
        return jsonify(envelope(None, f"Error: {e}", 500, False)), 500


@connect_api.route("/", methods=["PUT"])
def upsert_connect_profile():
    user_id = _current_user_id()
    data = request.get_json() or {}

    try:
        conn, cursor = db_connection()
        existing = _fetch_connect_profile_row(cursor, user_id)
        existing_account_type = _normalize_account_type(existing["account_type"]) if existing else None
        account_type = _normalize_account_type(data.get("account_type")) or existing_account_type
        if account_type is None:
            conn.close()
            return jsonify(envelope(None, "account_type must be farmer or importer", 400, False)), 400

        payload = {
            "account_type": account_type,
            "company": _safe_text(data.get("company")) or _safe_text(existing["company"] if existing else ""),
            "country": _safe_text(data.get("country")) or _safe_text(existing["country"] if existing else ""),
            "bio": _safe_text(data.get("bio")) or _safe_text(existing["bio"] if existing else ""),
            "min_order_qty": _safe_text(data.get("min_order_qty")) or _safe_text(existing["min_order_qty"] if existing else ""),
            "response_time": _safe_text(data.get("response_time")) or _safe_text(existing["response_time"] if existing else "") or "Within 24 hours",
        }
        _upsert_connect_profile(cursor, user_id, payload)
        conn.commit()
        row = _require_connect_profile(cursor, user_id)
        conn.close()
        return jsonify(envelope(_serialize_connect_profile(row), "Connect profile saved", 200)), 200
    except Exception as e:
        logger.exception("Failed to save connect profile for %s", user_id)
        return jsonify(envelope(None, f"Error: {e}", 500, False)), 500
