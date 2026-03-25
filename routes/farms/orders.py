import json
import logging
from datetime import datetime, timedelta

from flask import Blueprint, g, jsonify, request
from flask_jwt_extended import get_jwt_identity

from routes.farms.admin.dashboard import build_dashboard_states, percent_change
from database import db_connection
from decorators.roles import user_required
from extensions.redis_client import get_redis_client
from routes.api_envelope import build_meta, envelope, parse_pagination
from services.notifications import create_admin_notification


orders = Blueprint("orders", __name__)
logger = logging.getLogger(__name__)

ORDERS_LIST_CACHE_KEY_PREFIX = "farms:orders:list"
ORDER_DETAIL_CACHE_KEY_PREFIX = "farms:orders:item"
ORDER_USER_CACHE_KEY_PREFIX = "farms:orders:user"
ORDER_FARMER_CACHE_KEY_PREFIX = "farms:orders:farmer"
ORDER_STATS_CACHE_KEY = "farms:orders:stats:overview"
FARMER_DASHBOARD_CACHE_KEY_PREFIX = "farms:dashboard:summary"

ALLOWED_ORDER_STATUSES = {"pending", "processing", "completed", "cancelled"}


def _cache_get(key):
    try:
        redis_client = get_redis_client()
        value = redis_client.get(key)
        return json.loads(value) if value else None
    except Exception as e:
        logger.warning("Redis unavailable, skipping orders cache read: %s", e)
        return None


def _cache_set(key, payload, ttl=60):
    try:
        redis_client = get_redis_client()
        redis_client.setex(key, ttl, json.dumps(payload))
    except Exception as e:
        logger.warning("Redis unavailable, skipping orders cache write: %s", e)


def _cache_delete(*keys):
    if not keys:
        return
    try:
        redis_client = get_redis_client()
        redis_client.delete(*keys)
    except Exception as e:
        logger.warning("Redis unavailable, skipping orders cache delete: %s", e)


def _cache_delete_patterns(*patterns):
    try:
        redis_client = get_redis_client()
        keys = []
        for pattern in patterns:
            keys.extend(redis_client.keys(pattern))
        if keys:
            redis_client.delete(*keys)
    except Exception as e:
        logger.warning("Redis unavailable, skipping orders cache pattern delete: %s", e)


def _order_detail_cache_key(order_id):
    return f"{ORDER_DETAIL_CACHE_KEY_PREFIX}:{order_id}"


def _orders_list_cache_key(query_key):
    return f"{ORDERS_LIST_CACHE_KEY_PREFIX}:{query_key or 'default'}"


def _user_orders_cache_key(user_id, query_key):
    return f"{ORDER_USER_CACHE_KEY_PREFIX}:{user_id}:{query_key or 'default'}"


def _farmer_orders_cache_key(user_id, query_key):
    return f"{ORDER_FARMER_CACHE_KEY_PREFIX}:{user_id}:{query_key or 'default'}"


def _farmer_dashboard_cache_key(user_id):
    return f"{FARMER_DASHBOARD_CACHE_KEY_PREFIX}:{user_id}"


def _invalidate_orders_cache(order_id=None, user_id=None):
    keys = [ORDER_STATS_CACHE_KEY]
    if order_id is not None:
        keys.append(_order_detail_cache_key(order_id))
    if user_id is not None:
        keys.append(_farmer_dashboard_cache_key(user_id))
    _cache_delete(*keys)
    _cache_delete_patterns(
        f"{ORDERS_LIST_CACHE_KEY_PREFIX}:*",
        f"{ORDER_USER_CACHE_KEY_PREFIX}:*",
        f"{ORDER_FARMER_CACHE_KEY_PREFIX}:*",
        f"{FARMER_DASHBOARD_CACHE_KEY_PREFIX}:*",
    )


def _serialize_order_item(row):
    item = dict(row)
    item["quantity"] = int(item.get("quantity") or 0)
    item["unit_price"] = float(item.get("unit_price") or 0)
    item["line_total"] = round(item["quantity"] * item["unit_price"], 2)
    return item


def _serialize_order_row(row):
    item = dict(row)
    item["total_price"] = float(item.get("total_price") or 0)
    return item


def _sanitize_order_payload(payload):
    if not payload:
        return payload
    for item in payload.get("items", []):
        item.pop("product_owner_id", None)
    return payload


def _current_actor_name(default_value="A user"):
    current_user = getattr(g, "current_user", {}) or {}
    full_name = str(current_user.get("full_name") or "").strip()
    email = str(current_user.get("email") or "").strip()
    return full_name or email or default_value


def _order_href(order_id):
    return f"/orders/{int(order_id)}"


def _notify_admin_order_created(cursor, order_id, total_price, line_items_count):
    actor_name = _current_actor_name()
    create_admin_notification(
        cursor,
        "order",
        "New order created",
        (
            f"{actor_name} created order #{int(order_id)} with "
            f"{int(line_items_count)} item(s) totaling {float(total_price):.2f}."
        ),
        href=_order_href(order_id),
    )


def _notify_admin_order_updated(cursor, order_id, new_status, previous_status=None):
    actor_name = _current_actor_name()
    if previous_status and previous_status != new_status:
        description = (
            f"{actor_name} updated order #{int(order_id)} "
            f"from {previous_status} to {new_status}."
        )
    else:
        description = f"{actor_name} updated order #{int(order_id)} to {new_status}."

    create_admin_notification(
        cursor,
        "order",
        "Order updated",
        description,
        href=_order_href(order_id),
    )


def _get_order_with_items(cursor, order_id):
    cursor.execute(
        """
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
            o.updated_at
        FROM Orders o
        LEFT JOIN Users u ON u.id = o.user_id
        WHERE o.id = ?
        """,
        (order_id,),
    )
    order_row = cursor.fetchone()
    if not order_row:
        return None

    cursor.execute(
        """
        SELECT
            oi.id,
            oi.order_id,
            oi.product_id,
            oi.name,
            oi.quantity,
            oi.unit_price,
            oi.created_at,
            p.image_url,
            p.user_id AS product_owner_id
        FROM OrderItems oi
        LEFT JOIN Products p ON p.id = oi.product_id
        WHERE oi.order_id = ?
        ORDER BY oi.id ASC
        """,
        (order_id,),
    )
    items = [_serialize_order_item(row) for row in cursor.fetchall()]
    payload = _serialize_order_row(order_row)
    payload["items"] = items
    return payload


@orders.route("/get-user-orders", methods=["GET"])
@user_required
def get_user_orders():
    user_id = int(get_jwt_identity())
    page, per_page, offset = parse_pagination(request.args)

    cache_key = _user_orders_cache_key(user_id, request.query_string.decode("utf-8"))
    cached = _cache_get(cache_key)
    if cached is not None:
        return jsonify(envelope(cached.get("items", []), "User orders fetched", 200, True, cached.get("meta"))), 200

    try:
        conn, cursor = db_connection()
        cursor.execute("SELECT COUNT(*) AS total FROM Orders WHERE user_id = ?", (user_id,))
        total = int(cursor.fetchone()["total"] or 0)

        cursor.execute(
            """
            SELECT id
            FROM Orders
            WHERE user_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            (user_id, per_page, offset),
        )
        order_ids = [int(row["id"]) for row in cursor.fetchall()]

        items = []
        for order_id in order_ids:
            payload = _get_order_with_items(cursor, order_id)
            if payload:
                items.append(_sanitize_order_payload(payload))

        conn.close()
        meta = build_meta(page, per_page, total)
        _cache_set(cache_key, {"items": items, "meta": meta})
        return jsonify(envelope(items, "User orders fetched", 200, True, meta)), 200
    except Exception as e:
        logger.exception("Failed to fetch current user orders")
        return jsonify(envelope(None, f"Error: {e}", 500, False)), 500


@orders.route("/get-farmer-orders", methods=["GET"])
@user_required
def get_farmer_orders():
    farmer_id = int(get_jwt_identity())
    page, per_page, offset = parse_pagination(request.args)
    status = str(request.args.get("status") or "").strip().lower()

    if status and status not in ALLOWED_ORDER_STATUSES:
        return jsonify(envelope(None, "Invalid status filter", 400, False)), 400

    cache_key = _farmer_orders_cache_key(farmer_id, request.query_string.decode("utf-8"))
    cached = _cache_get(cache_key)
    if cached is not None:
        return jsonify(envelope(cached.get("items", []), "Farmer orders fetched", 200, True, cached.get("meta"))), 200

    where = ["p.user_id = ?"]
    params = [farmer_id]
    if status:
        where.append("LOWER(o.status) = ?")
        params.append(status)
    where_sql = " AND ".join(where)

    try:
        conn, cursor = db_connection()
        cursor.execute(
            f"""
            SELECT COUNT(DISTINCT o.id) AS total
            FROM Orders o
            JOIN OrderItems oi ON oi.order_id = o.id
            JOIN Products p ON p.id = oi.product_id
            WHERE {where_sql}
            """,
            tuple(params),
        )
        total = int(cursor.fetchone()["total"] or 0)

        query_params = list(params) + [per_page, offset]
        cursor.execute(
            f"""
            SELECT DISTINCT o.id
            FROM Orders o
            JOIN OrderItems oi ON oi.order_id = o.id
            JOIN Products p ON p.id = oi.product_id
            WHERE {where_sql}
            ORDER BY o.created_at DESC, o.id DESC
            LIMIT ? OFFSET ?
            """,
            tuple(query_params),
        )
        order_ids = [int(row["id"]) for row in cursor.fetchall()]

        payload_items = []
        for order_id in order_ids:
            order_payload = _get_order_with_items(cursor, order_id)
            if not order_payload:
                continue
            order_payload["items"] = [
                item for item in order_payload["items"]
                if item.get("product_id") is not None and int(item.get("product_owner_id") or 0) == farmer_id
            ]
            if order_payload["items"]:
                payload_items.append(_sanitize_order_payload(order_payload))

        conn.close()

        meta = build_meta(page, per_page, total)
        _cache_set(cache_key, {"items": payload_items, "meta": meta})
        return jsonify(envelope(payload_items, "Farmer orders fetched", 200, True, meta)), 200
    except Exception as e:
        logger.exception("Failed to fetch farmer orders")
        return jsonify(envelope(None, f"Error: {e}", 500, False)), 500


@orders.route("/create-order", methods=["POST"])
@user_required
def create_order():
    user_id = int(get_jwt_identity())
    data = request.get_json() or {}
    items = data.get("items")
    if not isinstance(items, list) or not items:
        return jsonify(envelope(None, "items is required and must be a non-empty array", 400, False)), 400

    payment_method = str(data.get("payment_method") or "").strip() or None
    shipping_address = str(data.get("shipping_address") or "").strip() or None
    notes = str(data.get("notes") or "").strip() or None

    try:
        conn, cursor = db_connection()
        normalized_items = []
        total_price = 0.0
        for item in items:
            try:
                product_id = int(item.get("product_id"))
                quantity = int(item.get("quantity", 1))
            except (TypeError, ValueError):
                conn.close()
                return jsonify(envelope(None, "Each item requires valid product_id and quantity", 400, False)), 400

            if quantity <= 0:
                conn.close()
                return jsonify(envelope(None, "Item quantity must be > 0", 400, False)), 400

            cursor.execute(
                "SELECT id, title, price FROM Products WHERE id = ? AND COALESCE(is_active, 1) = 1",
                (product_id,),
            )
            product = cursor.fetchone()
            if not product:
                conn.close()
                return jsonify(envelope(None, f"Product not found: {product_id}", 404, False)), 404

            unit_price = float(product["price"] or 0)
            line_total = unit_price * quantity
            total_price += line_total
            normalized_items.append(
                {
                    "product_id": product_id,
                    "name": product["title"],
                    "quantity": quantity,
                    "unit_price": unit_price,
                }
            )

        cursor.execute(
            """
            INSERT INTO Orders (user_id, status, total_price, payment_method, shipping_address, notes)
            VALUES (?, 'pending', ?, ?, ?, ?)
            """,
            (user_id, round(total_price, 2), payment_method, shipping_address, notes),
        )
        order_id = cursor.lastrowid

        for item in normalized_items:
            cursor.execute(
                """
                INSERT INTO OrderItems (user_id, order_id, product_id, name, quantity, unit_price)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    order_id,
                    item["product_id"],
                    item["name"],
                    item["quantity"],
                    item["unit_price"],
                ),
            )

        _notify_admin_order_created(
            cursor,
            order_id=order_id,
            total_price=round(total_price, 2),
            line_items_count=len(normalized_items),
        )
        conn.commit()
        payload = _get_order_with_items(cursor, order_id)
        conn.close()
        payload = _sanitize_order_payload(payload)

        _invalidate_orders_cache(order_id=order_id, user_id=user_id)
        return jsonify(envelope(payload, "Order created", 201)), 201
    except Exception as e:
        logger.exception("Failed to create order")
        return jsonify(envelope(None, f"Error: {e}", 500, False)), 500


@orders.route("/<int:order_id>/update", methods=["PUT"])
@user_required
def update_order_for_user(order_id):
    user_id = int(get_jwt_identity())
    data = request.get_json() or {}
    status = str(data.get("status") or "").strip().lower()
    if status not in ALLOWED_ORDER_STATUSES:
        return jsonify(envelope(None, "Invalid status", 400, False)), 400

    try:
        conn, cursor = db_connection()
        cursor.execute(
            "SELECT id, status FROM Orders WHERE id = ? AND user_id = ?",
            (order_id, user_id),
        )
        row = cursor.fetchone()
        if not row:
            conn.close()
            return jsonify(envelope(None, "Order not found or unauthorized", 404, False)), 404

        previous_status = str(row["status"] or "").strip().lower()
        cursor.execute(
            "UPDATE Orders SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (status, order_id),
        )
        if previous_status != status:
            _notify_admin_order_updated(
                cursor,
                order_id=order_id,
                new_status=status,
                previous_status=previous_status,
            )
        conn.commit()
        conn.close()
        _invalidate_orders_cache(order_id=order_id, user_id=user_id)
        return jsonify(envelope({"id": order_id, "status": status}, "Order updated", 200)), 200
    except Exception as e:
        logger.exception("Failed to update order %s for user", order_id)
        return jsonify(envelope(None, f"Error: {e}", 500, False)), 500


@orders.route("/<int:order_id>/delete", methods=["DELETE"])
@user_required
def delete_order_for_user(order_id):
    user_id = int(get_jwt_identity())
    try:
        conn, cursor = db_connection()
        cursor.execute(
            "SELECT status FROM Orders WHERE id = ? AND user_id = ?",
            (order_id, user_id),
        )
        row = cursor.fetchone()
        if not row:
            conn.close()
            return jsonify(envelope(None, "Order not found or unauthorized", 404, False)), 404
        if str(row["status"]).lower() != "pending":
            conn.close()
            return jsonify(envelope(None, "Only pending orders can be deleted", 403, False)), 403

        cursor.execute("DELETE FROM OrderItems WHERE order_id = ?", (order_id,))
        cursor.execute("DELETE FROM Orders WHERE id = ?", (order_id,))
        conn.commit()
        conn.close()
        _invalidate_orders_cache(order_id=order_id, user_id=user_id)
        return jsonify(envelope({"id": order_id}, "Order deleted", 200)), 200
    except Exception as e:
        logger.exception("Failed to delete order %s for user", order_id)
        return jsonify(envelope(None, f"Error: {e}", 500, False)), 500


@orders.route("/dashboard/stats", methods=["GET"])
@user_required
def get_farmer_dashboard_stats():
    farmer_id = int(get_jwt_identity())
    cache_key = _farmer_dashboard_cache_key(farmer_id)
    cached = _cache_get(cache_key)
    if cached is not None:
        return jsonify(envelope(cached, "Farmer dashboard stats fetched", 200)), 200

    try:
        now = datetime.now()
        current_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        previous_month_start = (current_month_start - timedelta(days=1)).replace(day=1)
        current_month_start_str = current_month_start.strftime("%Y-%m-%d %H:%M:%S")
        previous_month_start_str = previous_month_start.strftime("%Y-%m-%d %H:%M:%S")

        conn, cursor = db_connection()
        cursor.execute("SELECT COUNT(*) AS total FROM Products WHERE user_id = ? AND COALESCE(is_active, 1) = 1", (farmer_id,))
        total_products = int(cursor.fetchone()["total"] or 0)

        revenue_sql = """
            SELECT COALESCE(SUM(oi.quantity * oi.unit_price), 0) AS total
            FROM OrderItems oi
            JOIN Orders o ON o.id = oi.order_id
            JOIN Products p ON p.id = oi.product_id
            WHERE p.user_id = ? AND LOWER(o.status) = 'completed'
        """
        cursor.execute(revenue_sql, (farmer_id,))
        total_revenue = float(cursor.fetchone()["total"] or 0)
        cursor.execute(revenue_sql + " AND o.created_at >= ?", (farmer_id, current_month_start_str))
        current_month_revenue = float(cursor.fetchone()["total"] or 0)
        cursor.execute(
            revenue_sql + " AND o.created_at >= ? AND o.created_at < ?",
            (farmer_id, previous_month_start_str, current_month_start_str),
        )
        previous_month_revenue = float(cursor.fetchone()["total"] or 0)

        orders_sql = """
            SELECT COUNT(DISTINCT o.id) AS total
            FROM Orders o
            JOIN OrderItems oi ON oi.order_id = o.id
            JOIN Products p ON p.id = oi.product_id
            WHERE p.user_id = ?
        """
        cursor.execute(orders_sql, (farmer_id,))
        total_orders = int(cursor.fetchone()["total"] or 0)
        cursor.execute(orders_sql + " AND o.created_at >= ?", (farmer_id, current_month_start_str))
        current_month_orders = int(cursor.fetchone()["total"] or 0)
        cursor.execute(
            orders_sql + " AND o.created_at >= ? AND o.created_at < ?",
            (farmer_id, previous_month_start_str, current_month_start_str),
        )
        previous_month_orders = int(cursor.fetchone()["total"] or 0)

        customers_sql = """
            SELECT COUNT(DISTINCT o.user_id) AS total
            FROM Orders o
            JOIN OrderItems oi ON oi.order_id = o.id
            JOIN Products p ON p.id = oi.product_id
            WHERE p.user_id = ?
        """
        cursor.execute(customers_sql, (farmer_id,))
        total_customers = int(cursor.fetchone()["total"] or 0)
        cursor.execute(customers_sql + " AND o.created_at >= ?", (farmer_id, current_month_start_str))
        current_month_customers = int(cursor.fetchone()["total"] or 0)
        cursor.execute(
            customers_sql + " AND o.created_at >= ? AND o.created_at < ?",
            (farmer_id, previous_month_start_str, current_month_start_str),
        )
        previous_month_customers = int(cursor.fetchone()["total"] or 0)
        conn.close()

        payload = build_dashboard_states(
            total_revenue=total_revenue,
            revenue_change_percent=percent_change(current_month_revenue, previous_month_revenue),
            total_orders=total_orders,
            orders_change_percent=percent_change(current_month_orders, previous_month_orders),
            total_products=total_products,
            total_customers=total_customers,
            customers_change_percent=percent_change(current_month_customers, previous_month_customers),
        )
        _cache_set(cache_key, payload)
        return jsonify(envelope(payload, "Farmer dashboard stats fetched", 200)), 200
    except Exception as e:
        logger.exception("Failed to fetch farmer dashboard stats")
        return jsonify(envelope(None, f"Error: {e}", 500, False)), 500
