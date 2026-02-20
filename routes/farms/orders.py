import json
import logging

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity

from database import db_connection
from decorators.roles import user_required
from extensions.redis_client import get_redis_client
from routes import response


orders = Blueprint("orders", __name__)
logger = logging.getLogger(__name__)

ORDERS_LIST_CACHE_KEY = "farms:orders:list"
ORDER_CACHE_KEY_PREFIX = "farms:orders:item"
ORDERS_USER_CACHE_KEY_PREFIX = "farms:orders:user"
ORDERS_FARMER_CACHE_KEY_PREFIX = "farms:orders:farmer"


def _cache_get(key):
    try:
        redis_client = get_redis_client()
        payload = redis_client.get(key)
        return json.loads(payload) if payload else None
    except Exception as e:
        logger.warning("Redis unavailable, skipping orders cache read: %s", e)
        return None


def _cache_set(key, value, ttl=60):
    try:
        redis_client = get_redis_client()
        redis_client.setex(key, ttl, json.dumps(value))
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


def _order_cache_key(order_id):
    return f"{ORDER_CACHE_KEY_PREFIX}:{order_id}"


def _user_orders_cache_key(user_id):
    return f"{ORDERS_USER_CACHE_KEY_PREFIX}:{user_id}"


def _farmer_orders_cache_key(user_id):
    return f"{ORDERS_FARMER_CACHE_KEY_PREFIX}:{user_id}"


def _invalidate_order_cache(order_id=None, user_id=None):
    keys = [ORDERS_LIST_CACHE_KEY]
    if order_id is not None:
        keys.append(_order_cache_key(order_id))
    if user_id is not None:
        keys.append(_user_orders_cache_key(user_id))
        keys.append(_farmer_orders_cache_key(user_id))
    _cache_delete(*keys)
    _cache_delete_patterns(f"{ORDERS_FARMER_CACHE_KEY_PREFIX}:*")


@orders.route("/", methods=["GET"])
def get_orders():
    cached = _cache_get(ORDERS_LIST_CACHE_KEY)
    if cached is not None:
        logger.info("Orders list served from cache")
        return jsonify(response(cached, "Successfully retrieved orders.", 200)), 200

    try:
        conn, cursor = db_connection()
        cursor.execute("SELECT * FROM Orders")
        rows = cursor.fetchall()
        orders_payload = [dict(row) for row in rows]
        conn.close()

        _cache_set(ORDERS_LIST_CACHE_KEY, orders_payload)
        logger.info("Orders list loaded from DB")
        return jsonify(response(orders_payload, "Successfully retrieved orders.", 200)), 200
    except Exception as e:
        logger.exception("Failed to fetch orders list")
        return jsonify(response([], f"Error: {e}", 500)), 500


@orders.route("/<int:order_id>", methods=["GET"])
@user_required
def get_order(order_id):
    cache_key = _order_cache_key(order_id)
    cached = _cache_get(cache_key)
    if cached is not None:
        logger.info("Order %s served from cache", order_id)
        return jsonify(response(cached, "Successfully retrieved order.", 200)), 200

    try:
        conn, cursor = db_connection()
        cursor.execute("SELECT * FROM Orders WHERE id = ?", (order_id,))
        order = cursor.fetchone()
        if not order:
            conn.close()
            return jsonify(response([], "Order not found.", 404)), 404

        cursor.execute("SELECT * FROM OrderItems WHERE order_id = ?", (order_id,))
        items = cursor.fetchall()
        order_data = dict(order)
        order_data["items"] = [dict(item) for item in items]
        conn.close()

        _cache_set(cache_key, order_data)
        logger.info("Order %s loaded from DB", order_id)
        return jsonify(response(order_data, "Successfully retrieved order.", 200)), 200
    except Exception as e:
        logger.exception("Failed to fetch order %s", order_id)
        return jsonify(response([], f"Error: {e}", 500)), 500


@orders.route("/get-user-orders", methods=["GET"])
@user_required
def get_user_orders():
    try:
        user_id = get_jwt_identity()
        cache_key = _user_orders_cache_key(user_id)
        cached = _cache_get(cache_key)
        if cached is not None:
            logger.info("User orders served from cache for user %s", user_id)
            return jsonify(response(cached, "Successfully retrieved users's orders.", 200)), 200

        conn, cursor = db_connection()
        cursor.execute("SELECT * FROM Orders WHERE user_id = ?", (user_id,))
        rows = cursor.fetchall()
        orders_payload = [dict(row) for row in rows]

        for order in orders_payload:
            cursor.execute("SELECT * FROM OrderItems WHERE order_id = ?", (order["id"],))
            items = cursor.fetchall()
            order["items"] = [dict(item) for item in items]

        conn.close()

        _cache_set(cache_key, orders_payload)
        logger.info("User orders loaded from DB for user %s", user_id)
        return jsonify(response(orders_payload, "Successfully retrieved users's orders.", 200)), 200
    except Exception as e:
        logger.exception("Failed to fetch user orders")
        return jsonify(response([], f"Error: {e}", 500)), 500


@orders.route("/create-order", methods=["POST"])
@user_required
def create_order():
    try:
        user_id = get_jwt_identity()
        data = request.get_json() or {}

        if "items" not in data or not isinstance(data["items"], list) or not data["items"]:
            return jsonify(response([], "Invalid order data.", 400)), 400

        conn, cursor = db_connection()

        product_ids = tuple(item["product_id"] for item in data["items"])
        query = f"SELECT id FROM Products WHERE id IN ({','.join('?' for _ in product_ids)})"
        cursor.execute(query, product_ids)
        existing_ids = {row["id"] for row in cursor.fetchall()}

        missing_ids = [pid for pid in product_ids if pid not in existing_ids]
        if missing_ids:
            conn.close()
            return jsonify(response([], f"Product(s) not found: {missing_ids}", 404)), 404

        total_price = sum(item["unit_price"] * item["quantity"] for item in data["items"])

        cursor.execute(
            """
            INSERT INTO Orders (user_id, total_price, status)
            VALUES (?, ?, ?)
            """,
            (user_id, total_price, "pending"),
        )
        order_id = cursor.lastrowid

        for item in data["items"]:
            cursor.execute(
                """
                INSERT INTO OrderItems (order_id, user_id, product_id, name, quantity, unit_price)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    order_id,
                    user_id,
                    item["product_id"],
                    item.get("name", ""),
                    item["quantity"],
                    item["unit_price"],
                ),
            )

        conn.commit()
        conn.close()

        _invalidate_order_cache(order_id=order_id, user_id=user_id)
        logger.info("Order %s created for user %s", order_id, user_id)
        return jsonify(response({"order_id": order_id}, "Order created successfully.", 201)), 201
    except Exception as e:
        logger.exception("Failed to create order")
        return jsonify(response([], f"Error: {str(e)}", 500)), 500


@orders.route("/<int:order_id>/update", methods=["PUT"])
@user_required
def update_order(order_id):
    try:
        user_id = get_jwt_identity()
        data = request.get_json() or {}

        if "status" not in data:
            return jsonify(response([], "Status is required", 400)), 400

        conn, cursor = db_connection()
        cursor.execute("SELECT * FROM Orders WHERE id = ? AND user_id = ?", (order_id, user_id))
        order = cursor.fetchone()
        if not order:
            conn.close()
            return jsonify(response([], "Order not found or unauthorized", 404)), 404

        cursor.execute(
            """
            UPDATE Orders
            SET status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (data["status"], order_id),
        )

        conn.commit()
        conn.close()

        _invalidate_order_cache(order_id=order_id, user_id=user_id)
        logger.info("Order %s updated for user %s", order_id, user_id)
        return jsonify(response([], "Order updated successfully", 200)), 200
    except Exception as e:
        logger.exception("Failed to update order %s", order_id)
        return jsonify(response([], f"Error: {e}", 500)), 500


@orders.route("/<int:order_id>/delete", methods=["DELETE"])
@user_required
def delete_order(order_id):
    try:
        user_id = get_jwt_identity()
        conn, cursor = db_connection()

        cursor.execute("SELECT * FROM Orders WHERE id = ? AND user_id = ?", (order_id, user_id))
        order = cursor.fetchone()
        if not order:
            conn.close()
            return jsonify(response([], "Order not found or unauthorized", 404)), 404

        if order["status"] != "pending":
            conn.close()
            return jsonify(response([], "Only pending orders can be deleted", 403)), 403

        cursor.execute("DELETE FROM OrderItems WHERE order_id = ?", (order_id,))
        cursor.execute("DELETE FROM Orders WHERE id = ?", (order_id,))
        conn.commit()
        conn.close()

        _invalidate_order_cache(order_id=order_id, user_id=user_id)
        logger.info("Order %s deleted for user %s", order_id, user_id)
        return jsonify(response([], "Order deleted successfully", 200)), 200
    except Exception as e:
        logger.exception("Failed to delete order %s", order_id)
        return jsonify(response([], f"Error: {e}", 500)), 500


@orders.route("/get-farmer-orders", methods=["GET"])
@user_required
def get_farmer_orders():
    conn, cursor = None, None
    try:
        user_id = get_jwt_identity()
        cache_key = _farmer_orders_cache_key(user_id)
        cached = _cache_get(cache_key)
        if cached is not None:
            logger.info("Farmer orders served from cache for user %s", user_id)
            return jsonify(response(cached, "Successfully retrieved orders made to the farmer.", 200)), 200

        conn, cursor = db_connection()
        cursor.execute("SELECT * FROM Users WHERE id = ? AND user_type = ?", (user_id, "farmer"))
        farmer = cursor.fetchone()
        if not farmer:
            return jsonify(response([], "User is not a registered farmer", 404)), 404

        cursor.execute(
            """
            SELECT DISTINCT o.*
            FROM Orders o
            JOIN OrderItems oi ON o.id = oi.order_id
            JOIN Products p ON oi.product_id = p.id
            WHERE p.user_id = ?
            ORDER BY o.created_at DESC
            """,
            (user_id,),
        )
        rows = cursor.fetchall()
        orders_payload = [dict(row) for row in rows]

        for order in orders_payload:
            cursor.execute(
                """
                SELECT oi.*
                FROM OrderItems oi
                JOIN Products p ON oi.product_id = p.id
                WHERE oi.order_id = ? AND p.user_id = ?
                """,
                (order["id"], user_id),
            )
            items = cursor.fetchall()
            order["items"] = [dict(item) for item in items]

        _cache_set(cache_key, orders_payload)
        logger.info("Farmer orders loaded from DB for user %s", user_id)
        return jsonify(response(orders_payload, "Successfully retrieved orders made to the farmer.", 200)), 200
    except Exception as e:
        logger.exception("Failed to fetch farmer orders")
        return jsonify(response([], f"Error: {str(e)}", 500)), 500
    finally:
        if conn:
            conn.close()
