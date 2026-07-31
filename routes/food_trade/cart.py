from flask import jsonify, request
from flask_jwt_extended import jwt_required

from database.connection import db_connection
from middleware.authMiddleware import get_authenticated_user_id
from routes.api_envelope import envelope
from . import food_trade_api

@food_trade_api.route("/cart", methods=["GET"])
@jwt_required()
def get_cart():
    user_id = get_authenticated_user_id()
    if not user_id:
        return jsonify(envelope(None, "Unauthorized", 401, False)), 401

    conn, cursor = db_connection()
    try:
        cursor.execute(
            """
            SELECT c.id, c.product_id, c.quantity, 
                   p.name, p.price_ghs, p.image_url, p.is_active
            FROM food_trade_carts c
            JOIN food_trade_products p ON c.product_id = p.id
            WHERE c.user_id = ?
            ORDER BY c.created_at DESC
            """, (user_id,)
        )
        items = [dict(row) for row in cursor.fetchall()]
        return jsonify(envelope(items, "Cart retrieved successfully", 200, True)), 200
    except Exception as exc:
        return jsonify(envelope(None, str(exc), 500, False)), 500
    finally:
        conn.close()

@food_trade_api.route("/cart", methods=["POST"])
@jwt_required()
def add_to_cart():
    user_id = get_authenticated_user_id()
    if not user_id:
        return jsonify(envelope(None, "Unauthorized", 401, False)), 401

    data = request.json or {}
    product_id = data.get("product_id")
    quantity = int(data.get("quantity", 1))

    if not product_id or quantity < 1:
        return jsonify(envelope(None, "Invalid product or quantity", 400, False)), 400

    conn, cursor = db_connection()
    try:
        # Verify product exists and is active
        cursor.execute("SELECT id, is_active FROM food_trade_products WHERE id = ?", (product_id,))
        prod = cursor.fetchone()
        if not prod or not prod["is_active"]:
            return jsonify(envelope(None, "Product unavailable", 400, False)), 400

        # Check if already in cart
        cursor.execute("SELECT id, quantity FROM food_trade_carts WHERE user_id = ? AND product_id = ?", (user_id, product_id))
        cart_item = cursor.fetchone()

        if cart_item:
            new_qty = cart_item["quantity"] + quantity
            cursor.execute(
                "UPDATE food_trade_carts SET quantity = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (new_qty, cart_item["id"])
            )
        else:
            cursor.execute(
                "INSERT INTO food_trade_carts (user_id, product_id, quantity) VALUES (?, ?, ?)",
                (user_id, product_id, quantity)
            )
            
        conn.commit()
        return jsonify(envelope(None, "Added to cart successfully", 200, True)), 200
    except Exception as exc:
        conn.rollback()
        return jsonify(envelope(None, str(exc), 500, False)), 500
    finally:
        conn.close()

@food_trade_api.route("/cart/<int:item_id>", methods=["PUT"])
@jwt_required()
def update_cart_item(item_id):
    user_id = get_authenticated_user_id()
    if not user_id:
        return jsonify(envelope(None, "Unauthorized", 401, False)), 401

    data = request.json or {}
    quantity = data.get("quantity")

    if quantity is None or int(quantity) < 1:
        return jsonify(envelope(None, "Invalid quantity", 400, False)), 400

    conn, cursor = db_connection()
    try:
        cursor.execute("SELECT id FROM food_trade_carts WHERE id = ? AND user_id = ?", (item_id, user_id))
        if not cursor.fetchone():
            return jsonify(envelope(None, "Cart item not found", 404, False)), 404

        cursor.execute(
            "UPDATE food_trade_carts SET quantity = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (int(quantity), item_id)
        )
        conn.commit()
        return jsonify(envelope(None, "Cart updated successfully", 200, True)), 200
    except Exception as exc:
        conn.rollback()
        return jsonify(envelope(None, str(exc), 500, False)), 500
    finally:
        conn.close()

@food_trade_api.route("/cart/<int:item_id>", methods=["DELETE"])
@jwt_required()
def remove_cart_item(item_id):
    user_id = get_authenticated_user_id()
    if not user_id:
        return jsonify(envelope(None, "Unauthorized", 401, False)), 401

    conn, cursor = db_connection()
    try:
        cursor.execute("SELECT id FROM food_trade_carts WHERE id = ? AND user_id = ?", (item_id, user_id))
        if not cursor.fetchone():
            return jsonify(envelope(None, "Cart item not found", 404, False)), 404

        cursor.execute("DELETE FROM food_trade_carts WHERE id = ?", (item_id,))
        conn.commit()
        return jsonify(envelope(None, "Item removed from cart", 200, True)), 200
    except Exception as exc:
        conn.rollback()
        return jsonify(envelope(None, str(exc), 500, False)), 500
    finally:
        conn.close()

@food_trade_api.route("/cart", methods=["DELETE"])
@jwt_required()
def clear_cart():
    user_id = get_authenticated_user_id()
    if not user_id:
        return jsonify(envelope(None, "Unauthorized", 401, False)), 401

    conn, cursor = db_connection()
    try:
        cursor.execute("DELETE FROM food_trade_carts WHERE user_id = ?", (user_id,))
        conn.commit()
        return jsonify(envelope(None, "Cart cleared successfully", 200, True)), 200
    except Exception as exc:
        conn.rollback()
        return jsonify(envelope(None, str(exc), 500, False)), 500
    finally:
        conn.close()
