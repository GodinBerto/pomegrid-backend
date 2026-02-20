import json
import logging

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity

from database import db_connection
from decorators.roles import user_required
from extensions.redis_client import get_redis_client
from routes import response


carts = Blueprint("carts", __name__)
logger = logging.getLogger(__name__)


def _cache_get(key):
    try:
        redis_client = get_redis_client()
        payload = redis_client.get(key)
        return json.loads(payload) if payload else None
    except Exception as e:
        logger.warning("Redis unavailable, skipping cart cache read: %s", e)
        return None


def _cache_set(key, value, ttl=60):
    try:
        redis_client = get_redis_client()
        redis_client.setex(key, ttl, json.dumps(value))
    except Exception as e:
        logger.warning("Redis unavailable, skipping cart cache write: %s", e)


def _cache_delete(*keys):
    if not keys:
        return
    try:
        redis_client = get_redis_client()
        redis_client.delete(*keys)
    except Exception as e:
        logger.warning("Redis unavailable, skipping cart cache delete: %s", e)


def _user_cart_cache_key(user_id):
    return f"farms:carts:user:{user_id}"


@carts.route("/", methods=["POST"])
@user_required
def add_to_cart():
    try:
        user_id = get_jwt_identity()
        data = request.get_json() or {}

        if "product_id" not in data or "quantity" not in data:
            return jsonify(response([], "Missing product_id or quantity", 400)), 400

        product_id = data["product_id"]
        quantity = data["quantity"]

        conn, cursor = db_connection()

        cursor.execute("SELECT * FROM Products WHERE id = ?", (product_id,))
        product = cursor.fetchone()
        if not product:
            conn.close()
            return jsonify(response([], "Product not found", 404)), 404

        cursor.execute(
            "SELECT * FROM Cart WHERE user_id = ? AND product_id = ?",
            (user_id, product_id),
        )
        existing = cursor.fetchone()

        if existing:
            cursor.execute(
                "UPDATE Cart SET quantity = quantity + ? WHERE user_id = ? AND product_id = ?",
                (quantity, user_id, product_id),
            )
        else:
            cursor.execute(
                "INSERT INTO Cart (user_id, product_id, quantity) VALUES (?, ?, ?)",
                (user_id, product_id, quantity),
            )

        conn.commit()

        cursor.execute(
            """
            SELECT Cart.id, Cart.product_id, Cart.quantity,
                   Products.title, Products.price, Products.image_url
            FROM Cart
            JOIN Products ON Cart.product_id = Products.id
            WHERE Cart.user_id = ? AND Cart.product_id = ?
            """,
            (user_id, product_id),
        )
        cart_item = cursor.fetchone()
        conn.close()

        _cache_delete(_user_cart_cache_key(user_id))
        logger.info("Cart item added/updated for user %s, product %s", user_id, product_id)

        payload = {
            "id": cart_item[0],
            "product_id": cart_item[1],
            "quantity": cart_item[2],
            "title": cart_item[3],
            "price": cart_item[4],
            "image_url": cart_item[5],
        }
        return jsonify(response(payload, "Item added to cart", 201)), 201
    except Exception as e:
        logger.exception("Failed to add item to cart")
        return jsonify(response([], f"Error: {str(e)}", 500)), 500


@carts.route("/", methods=["GET"])
@user_required
def get_carts():
    try:
        user_id = get_jwt_identity()
        cache_key = _user_cart_cache_key(user_id)
        cached = _cache_get(cache_key)
        if cached is not None:
            logger.info("Cart served from cache for user %s", user_id)
            return jsonify(response(cached, "Successfully retrieved cart items.", 200)), 200

        conn, cursor = db_connection()
        cursor.execute(
            """
            SELECT
                Cart.id AS cart_id,
                Cart.quantity,
                Products.id AS product_id,
                Products.title AS name,
                Products.price,
                Products.image_url AS image
            FROM Cart
            JOIN Products ON Cart.product_id = Products.id
            WHERE Cart.user_id = ?
            """,
            (user_id,),
        )

        rows = cursor.fetchall()
        carts_payload = []
        for row in rows:
            item = dict(row)
            item["totalPrice"] = item["price"] * item["quantity"]
            carts_payload.append(item)

        conn.close()
        _cache_set(cache_key, carts_payload)
        logger.info("Cart loaded from DB for user %s", user_id)
        return jsonify(response(carts_payload, "Successfully retrieved cart items.", 200)), 200
    except Exception as e:
        logger.exception("Failed to fetch cart")
        return jsonify(response([], f"Error: {str(e)}", 500)), 500


@carts.route("/<int:cart_id>", methods=["PUT"])
@user_required
def update_cart_item(cart_id):
    try:
        user_id = get_jwt_identity()
        data = request.get_json() or {}

        if "quantity" not in data:
            return jsonify(response([], "Missing quantity", 400)), 400

        quantity = data["quantity"]
        if quantity <= 0:
            return jsonify(response([], "Quantity must be greater than 0", 400)), 400

        conn, cursor = db_connection()
        cursor.execute("SELECT * FROM Cart WHERE id = ? AND user_id = ?", (cart_id, user_id))
        item = cursor.fetchone()
        if not item:
            conn.close()
            return jsonify(response([], "Cart item not found", 404)), 404

        cursor.execute(
            "UPDATE Cart SET quantity = ? WHERE id = ? AND user_id = ?",
            (quantity, cart_id, user_id),
        )
        conn.commit()

        cursor.execute(
            """
            SELECT
                Cart.id AS cart_id,
                Cart.quantity,
                Products.id AS product_id,
                Products.title AS name,
                Products.price,
                Products.image_url AS image
            FROM Cart
            JOIN Products ON Cart.product_id = Products.id
            WHERE Cart.id = ? AND Cart.user_id = ?
            """,
            (cart_id, user_id),
        )
        updated_item = cursor.fetchone()
        conn.close()

        if not updated_item:
            return jsonify(response([], "Updated cart item not found", 404)), 404

        updated_data = dict(updated_item)
        updated_data["totalPrice"] = updated_data["price"] * updated_data["quantity"]
        _cache_delete(_user_cart_cache_key(user_id))
        logger.info("Cart item %s updated for user %s", cart_id, user_id)
        return jsonify(response(updated_data, "Cart item updated", 200)), 200
    except Exception as e:
        logger.exception("Failed to update cart item %s", cart_id)
        return jsonify(response([], f"Error: {str(e)}", 500)), 500


@carts.route("/<int:cart_id>", methods=["DELETE"])
@user_required
def delete_cart_item(cart_id):
    try:
        user_id = get_jwt_identity()
        conn, cursor = db_connection()

        cursor.execute("SELECT 1 FROM Cart WHERE id = ? AND user_id = ?", (cart_id, user_id))
        if not cursor.fetchone():
            conn.close()
            return jsonify(response([], "Cart item not found", 404)), 404

        cursor.execute("DELETE FROM Cart WHERE id = ? AND user_id = ?", (cart_id, user_id))
        conn.commit()
        conn.close()

        _cache_delete(_user_cart_cache_key(user_id))
        logger.info("Cart item %s deleted for user %s", cart_id, user_id)
        return jsonify(response([], "Cart item deleted", 200)), 200
    except Exception as e:
        logger.exception("Failed to delete cart item %s", cart_id)
        return jsonify(response([], f"Error: {str(e)}", 500)), 500


@carts.route("/clear", methods=["DELETE"])
@user_required
def clear_cart():
    try:
        user_id = get_jwt_identity()
        conn, cursor = db_connection()
        cursor.execute("DELETE FROM Cart WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()

        _cache_delete(_user_cart_cache_key(user_id))
        logger.info("Cart cleared for user %s", user_id)
        return jsonify(response([], "All cart items cleared", 200)), 200
    except Exception as e:
        logger.exception("Failed to clear cart")
        return jsonify(response([], f"Error: {str(e)}", 500)), 500
