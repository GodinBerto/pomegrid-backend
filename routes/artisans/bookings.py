import re
import uuid
import logging
from datetime import date, datetime

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from database import db_connection
from decorators.roles import admin_required
from extensions.redis_client import get_redis_client

bookings = Blueprint("bookings", __name__)
logger = logging.getLogger(__name__)

ALLOWED_BOOKING_STATUSES = {
    "pending",
    "accepted",
    "confirmed",
    "in_progress",
    "rejected",
    "completed",
    "cancelled",
}


def _api_response(data, message, http_status=200, status=True):
    return jsonify({"status": status, "message": message, "data": data}), http_status


def _serialize_booking(row):
    booking = dict(row)
    if booking.get("estimated_price") is not None:
        booking["estimated_price"] = int(booking["estimated_price"])
    if booking.get("service_id") is not None:
        booking["service_id"] = int(booking["service_id"])
    return booking


def _is_valid_phone(value):
    digits = re.sub(r"\D", "", str(value or ""))
    return len(digits) >= 10


def _invalidate_admin_cache():
    try:
        redis_client = get_redis_client()
        keys = redis_client.keys("admin:*")
        if keys:
            redis_client.delete(*keys)
    except Exception as e:
        logger.warning("Redis unavailable, skipping admin cache invalidate: %s", e)


def _invalidate_worker_dashboard_cache(worker_id):
    try:
        conn, cursor = db_connection()
        cursor.execute(
            """
            SELECT user_id
            FROM worker_profiles
            WHERE legacy_worker_id = ?
            """,
            (worker_id,),
        )
        rows = cursor.fetchall()
        conn.close()

        user_ids = {int(worker_id)}
        for row in rows:
            if row["user_id"] is not None:
                user_ids.add(int(row["user_id"]))

        redis_client = get_redis_client()
        keys = []
        for user_id in user_ids:
            keys.extend(redis_client.keys(f"worker:dashboard:summary:{user_id}"))
        if keys:
            redis_client.delete(*keys)
    except Exception as e:
        logger.warning("Redis unavailable, skipping worker cache invalidate: %s", e)


@bookings.route("/workers/<int:worker_id>/bookings", methods=["POST"])
@jwt_required()
def create_booking(worker_id):
    try:
        user_id = int(get_jwt_identity())
    except (TypeError, ValueError):
        return _api_response(None, "Invalid authenticated user", 401, False)
    data = request.get_json() or {}

    service_id = data.get("service_id")
    service_code = (data.get("service_code") or "").strip()
    custom_service_text = (data.get("custom_service_text") or "").strip()
    requested_date_raw = (data.get("requested_date") or "").strip()
    scheduled_time = (data.get("scheduled_time") or "").strip()
    customer_phone = (data.get("customer_phone") or "").strip()
    service_address = (data.get("service_address") or "").strip()
    job_description = (data.get("job_description") or "").strip()
    estimated_price = data.get("estimated_price")

    if service_id in ("", None):
        service_id = None
    else:
        try:
            service_id = int(service_id)
        except (TypeError, ValueError):
            return _api_response(None, "service_id must be an integer", 400, False)

    if not service_code:
        return _api_response(None, "service_code is required", 400, False)

    if not requested_date_raw:
        return _api_response(None, "requested_date is required", 400, False)

    try:
        requested_date = datetime.strptime(requested_date_raw, "%Y-%m-%d").date()
    except ValueError:
        return _api_response(None, "requested_date must be YYYY-MM-DD", 400, False)

    if requested_date < date.today():
        return _api_response(None, "requested_date must be today or a future date", 400, False)

    if not customer_phone:
        return _api_response(None, "customer_phone is required", 400, False)
    if not _is_valid_phone(customer_phone):
        return _api_response(None, "customer_phone must contain at least 10 digits", 400, False)

    if not service_address:
        return _api_response(None, "service_address is required", 400, False)
    if not job_description:
        return _api_response(None, "job_description is required", 400, False)

    if service_code == "other" and not custom_service_text:
        return _api_response(None, "custom_service_text is required when service_code is 'other'", 400, False)

    if estimated_price in ("", None):
        estimated_price = None
    else:
        try:
            estimated_price = int(estimated_price)
        except (TypeError, ValueError):
            return _api_response(None, "estimated_price must be an integer", 400, False)
    booking_code = (data.get("code") or f"BK-{uuid.uuid4().hex[:10]}").strip()

    try:
        conn, cursor = db_connection()
        cursor.execute("SELECT id, is_active FROM Users WHERE id = ?", (user_id,))
        user = cursor.fetchone()
        if not user:
            conn.close()
            return _api_response(None, "User not found", 404, False)
        if not user["is_active"]:
            conn.close()
            return _api_response(None, "User account is inactive", 403, False)

        cursor.execute("SELECT id FROM Workers WHERE id = ?", (worker_id,))
        worker = cursor.fetchone()
        if not worker:
            conn.close()
            return _api_response(None, "Worker not found", 404, False)

        resolved_service_id = service_id
        resolved_service_name = None

        if service_id is not None:
            cursor.execute(
                """
                SELECT id, service_code, service_name
                FROM worker_services
                WHERE id = ? AND worker_id = ?
                """,
                (service_id, worker_id),
            )
            service_row = cursor.fetchone()
            if not service_row:
                conn.close()
                return _api_response(None, "service_id must belong to the worker", 400, False)

            if service_code != "other" and service_code != service_row["service_code"]:
                conn.close()
                return _api_response(None, "service_code does not match the selected service_id", 400, False)

            service_code = service_row["service_code"]
            resolved_service_name = service_row["service_name"]
        elif service_code != "other":
            cursor.execute(
                """
                SELECT id, service_name
                FROM worker_services
                WHERE worker_id = ? AND service_code = ? AND COALESCE(is_active, 1) = 1
                LIMIT 1
                """,
                (worker_id, service_code),
            )
            service_row = cursor.fetchone()
            if service_row:
                resolved_service_id = service_row["id"]
                resolved_service_name = service_row["service_name"]

        cursor.execute(
            """
            INSERT INTO bookings (
                code, worker_id, user_id, customer_id, service_id, service_code, service_name,
                service_name_snapshot, custom_service_text, requested_date, scheduled_date,
                scheduled_time, customer_phone, service_address, address, job_description,
                description, estimated_price, total_price, is_custom_service
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                booking_code,
                worker_id,
                user_id,
                user_id,
                resolved_service_id,
                service_code,
                resolved_service_name,
                resolved_service_name,
                custom_service_text if custom_service_text else None,
                requested_date.isoformat(),
                requested_date.isoformat(),
                scheduled_time if scheduled_time else None,
                customer_phone,
                service_address,
                service_address,
                job_description,
                job_description,
                estimated_price,
                estimated_price,
                1 if service_code == "other" else 0,
            ),
        )
        booking_id = cursor.lastrowid
        conn.commit()

        cursor.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,))
        row = cursor.fetchone()
        conn.close()
        _invalidate_admin_cache()
        _invalidate_worker_dashboard_cache(worker_id)

        return _api_response(_serialize_booking(row), "Booking request sent", 201, True)
    except Exception as e:
        return _api_response(None, f"Error: {e}", 500, False)


@bookings.route("/bookings/<int:booking_id>", methods=["GET"])
def get_booking(booking_id):
    try:
        conn, cursor = db_connection()
        cursor.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,))
        row = cursor.fetchone()
        conn.close()

        if not row:
            return _api_response(None, "Booking not found", 404, False)

        return _api_response(_serialize_booking(row), "Booking fetched", 200, True)
    except Exception as e:
        return _api_response(None, f"Error: {e}", 500, False)


@bookings.route("/bookings/<int:booking_id>/status", methods=["PATCH"])
@admin_required
def update_booking_status(booking_id):
    data = request.get_json() or {}
    status = (data.get("status") or "").strip().lower()

    if status not in ALLOWED_BOOKING_STATUSES:
        return _api_response(None, "Invalid status", 400, False)

    try:
        conn, cursor = db_connection()
        cursor.execute("SELECT id FROM bookings WHERE id = ?", (booking_id,))
        booking = cursor.fetchone()
        if not booking:
            conn.close()
            return _api_response(None, "Booking not found", 404, False)

        cursor.execute(
            """
            UPDATE bookings
            SET status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (status, booking_id),
        )
        conn.commit()
        cursor.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,))
        row = cursor.fetchone()
        worker_id = row["worker_id"]
        conn.close()
        _invalidate_admin_cache()
        _invalidate_worker_dashboard_cache(worker_id)

        return _api_response(_serialize_booking(row), "Booking status updated", 200, True)
    except Exception as e:
        return _api_response(None, f"Error: {e}", 500, False)
