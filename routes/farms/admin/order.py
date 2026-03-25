import logging

from flask import Blueprint, jsonify, request

from database import db_connection
from decorators.roles import admin_required
from routes.api_envelope import build_meta, envelope, parse_pagination
from routes.farms.orders import (
    ALLOWED_ORDER_STATUSES,
    ORDER_STATS_CACHE_KEY,
    _cache_get,
    _cache_set,
    _get_order_with_items,
    _invalidate_orders_cache,
    _order_detail_cache_key,
    _orders_list_cache_key,
    _sanitize_order_payload,
    _serialize_order_row,
)
from services.notifications import create_admin_notification, create_user_notification


orders_admin = Blueprint("orders_admin", __name__)
logger = logging.getLogger(__name__)


@orders_admin.route("", methods=["GET"])
@orders_admin.route("/", methods=["GET"])
@admin_required
def list_orders_admin():
    page, per_page, offset = parse_pagination(request.args)

    search = str(request.args.get("search") or "").strip()
    status = str(request.args.get("status") or "").strip().lower()
    date_from = str(request.args.get("date_from") or "").strip()
    date_to = str(request.args.get("date_to") or "").strip()
    sort_by = str(request.args.get("sort_by") or "date").strip().lower()
    sort_dir = str(request.args.get("sort_dir") or "desc").strip().lower()

    if status and status not in ALLOWED_ORDER_STATUSES:
        return jsonify(envelope(None, "Invalid status filter", 400, False)), 400

    sort_fields = {"date": "o.created_at", "total": "o.total_price"}
    order_field = sort_fields.get(sort_by, "o.created_at")
    direction = "ASC" if sort_dir == "asc" else "DESC"

    cache_key = _orders_list_cache_key(request.query_string.decode("utf-8"))
    cached = _cache_get(cache_key)
    if cached is not None:
        return jsonify(envelope(cached.get("items", []), "Orders fetched", 200, True, cached.get("meta"))), 200

    where = ["1=1"]
    params = []

    if search:
        like = f"%{search}%"
        where.append(
            "(CAST(o.id AS TEXT) LIKE ? OR LOWER(COALESCE(u.full_name, '')) LIKE LOWER(?) OR LOWER(COALESCE(u.email, '')) LIKE LOWER(?))"
        )
        params.extend([like, like, like])

    if status:
        where.append("LOWER(o.status) = ?")
        params.append(status)

    if date_from:
        where.append("o.created_at >= ?")
        params.append(date_from)

    if date_to:
        where.append("o.created_at <= ?")
        params.append(date_to)

    where_sql = " AND ".join(where)

    try:
        conn, cursor = db_connection()
        cursor.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM Orders o
            LEFT JOIN Users u ON u.id = o.user_id
            WHERE {where_sql}
            """,
            tuple(params),
        )
        total = int(cursor.fetchone()["total"] or 0)

        query_params = list(params) + [per_page, offset]
        cursor.execute(
            f"""
            SELECT
                o.id,
                o.user_id,
                u.full_name AS user_full_name,
                u.email AS user_email,
                o.status,
                o.total_price,
                o.payment_method,
                o.shipping_address,
                o.notes,
                o.created_at,
                o.updated_at,
                COUNT(oi.id) AS items_count
            FROM Orders o
            LEFT JOIN Users u ON u.id = o.user_id
            LEFT JOIN OrderItems oi ON oi.order_id = o.id
            WHERE {where_sql}
            GROUP BY o.id
            ORDER BY {order_field} {direction}, o.id DESC
            LIMIT ? OFFSET ?
            """,
            tuple(query_params),
        )
        rows = cursor.fetchall()
        conn.close()

        items = []
        for row in rows:
            serialized = _serialize_order_row(row)
            serialized["items_count"] = int(serialized.get("items_count") or 0)
            items.append(serialized)

        meta = build_meta(page, per_page, total)
        _cache_set(cache_key, {"items": items, "meta": meta})
        return jsonify(envelope(items, "Orders fetched", 200, True, meta)), 200
    except Exception as e:
        logger.exception("Failed to list admin orders")
        return jsonify(envelope(None, f"Error: {e}", 500, False)), 500


@orders_admin.route("/<int:order_id>", methods=["GET"])
@admin_required
def get_order_admin(order_id):
    cache_key = _order_detail_cache_key(order_id)
    cached = _cache_get(cache_key)
    if cached is not None:
        return jsonify(envelope(cached, "Order fetched", 200)), 200

    try:
        conn, cursor = db_connection()
        payload = _get_order_with_items(cursor, order_id)
        conn.close()
        if not payload:
            return jsonify(envelope(None, "Order not found", 404, False)), 404

        payload = _sanitize_order_payload(payload)
        _cache_set(cache_key, payload)
        return jsonify(envelope(payload, "Order fetched", 200)), 200
    except Exception as e:
        logger.exception("Failed to fetch order %s", order_id)
        return jsonify(envelope(None, f"Error: {e}", 500, False)), 500


@orders_admin.route("/<int:order_id>/status", methods=["PATCH"])
@admin_required
def patch_order_status(order_id):
    data = request.get_json() or {}
    status = str(data.get("status") or "").strip().lower()
    if status not in ALLOWED_ORDER_STATUSES:
        return jsonify(envelope(None, "Invalid status", 400, False)), 400

    try:
        conn, cursor = db_connection()
        cursor.execute("SELECT id, user_id, status FROM Orders WHERE id = ?", (order_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return jsonify(envelope(None, "Order not found", 404, False)), 404

        previous_status = str(row["status"] or "").strip().lower()
        cursor.execute(
            """
            UPDATE Orders
            SET status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (status, order_id),
        )
        if previous_status != status:
            create_admin_notification(
                cursor,
                "order",
                "Order updated",
                f"Order #{int(order_id)} status changed from {previous_status} to {status}.",
                href=f"/orders/{int(order_id)}",
            )
            create_user_notification(
                cursor,
                row["user_id"],
                "order_status",
                "Order updated",
                f"Your order #{int(order_id)} changed from {previous_status} to {status}.",
                payload={
                    "order_id": int(order_id),
                    "status": str(status),
                    "previous_status": previous_status,
                },
            )
        conn.commit()
        conn.close()

        _invalidate_orders_cache(order_id=order_id, user_id=row["user_id"])
        return jsonify(envelope({"id": order_id, "status": status}, "Order status updated", 200)), 200
    except Exception as e:
        logger.exception("Failed to patch order status for %s", order_id)
        return jsonify(envelope(None, f"Error: {e}", 500, False)), 500


@orders_admin.route("/stats/overview", methods=["GET"])
@admin_required
def admin_orders_stats_overview():
    cached = _cache_get(ORDER_STATS_CACHE_KEY)
    if cached is not None:
        return jsonify(envelope(cached, "Order stats fetched", 200)), 200

    try:
        conn, cursor = db_connection()
        cursor.execute("SELECT COUNT(*) AS c FROM Orders")
        total_orders = int(cursor.fetchone()["c"] or 0)
        cursor.execute("SELECT COUNT(*) AS c FROM Orders WHERE LOWER(status) = 'pending'")
        pending_orders = int(cursor.fetchone()["c"] or 0)
        cursor.execute("SELECT COUNT(*) AS c FROM Orders WHERE LOWER(status) = 'processing'")
        processing_orders = int(cursor.fetchone()["c"] or 0)
        cursor.execute("SELECT COUNT(*) AS c FROM Orders WHERE LOWER(status) = 'completed'")
        completed_orders = int(cursor.fetchone()["c"] or 0)
        cursor.execute("SELECT COUNT(*) AS c FROM Orders WHERE LOWER(status) = 'cancelled'")
        cancelled_orders = int(cursor.fetchone()["c"] or 0)
        cursor.execute("SELECT COALESCE(SUM(total_price), 0) AS v FROM Orders WHERE LOWER(status) = 'completed'")
        completed_revenue = float(cursor.fetchone()["v"] or 0)
        conn.close()

        payload = {
            "totalOrders": total_orders,
            "pendingOrders": pending_orders,
            "processingOrders": processing_orders,
            "completedOrders": completed_orders,
            "cancelledOrders": cancelled_orders,
            "completedRevenue": round(completed_revenue, 2),
        }
        _cache_set(ORDER_STATS_CACHE_KEY, payload)
        return jsonify(envelope(payload, "Order stats fetched", 200)), 200
    except Exception as e:
        logger.exception("Failed to fetch admin order stats")
        return jsonify(envelope(None, f"Error: {e}", 500, False)), 500
