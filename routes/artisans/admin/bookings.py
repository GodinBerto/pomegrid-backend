from flask import Blueprint

from database import db_connection
from decorators.roles import admin_required
from routes.artisans.bookings import (
    ALLOWED_BOOKING_STATUSES,
    _api_response,
    _invalidate_admin_cache,
    _invalidate_worker_dashboard_cache,
    _serialize_booking,
)


bookings_admin = Blueprint("bookings_admin", __name__)


@bookings_admin.route("/bookings/<int:booking_id>/status", methods=["PATCH"])
@admin_required
def update_booking_status(booking_id):
    from flask import request

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
