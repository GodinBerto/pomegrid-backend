from flask import request, jsonify
from flask_jwt_extended import jwt_required
from database import db_connection
from routes.api_envelope import envelope
from .utils import check_admin
from middleware.authMiddleware import get_authenticated_user_id
from . import food_trade_api

@food_trade_api.route("/weekly_products", methods=["GET"])
def get_weekly_products():
    conn, cursor = db_connection()
    try:
        cursor.execute(
            """
            SELECT id, name, description, price, image_url, status, created_at, updated_at
            FROM food_trade_weekly_products
            WHERE status = 'active'
            ORDER BY created_at DESC
            """
        )
        rows = cursor.fetchall()
        products = [dict(row) for row in rows]
        return jsonify(envelope(products, "Weekly products retrieved successfully.", 200)), 200
    except Exception as exc:
        return jsonify(envelope(None, "Internal server error", 500, False)), 500
    finally:
        conn.close()

@food_trade_api.route("/weekly_products/<int:product_id>", methods=["GET"])
def get_weekly_product_by_id(product_id):
    conn, cursor = db_connection()
    try:
        cursor.execute(
            """
            SELECT id, name, description, price, image_url, status, created_at, updated_at
            FROM food_trade_weekly_products
            WHERE id = ?
            """, (product_id,)
        )
        row = cursor.fetchone()
        if not row:
            return jsonify(envelope(None, "Product not found", 404, False)), 404
            
        return jsonify(envelope(dict(row), "Product retrieved successfully.", 200)), 200
    except Exception as exc:
        return jsonify(envelope(None, "Internal server error", 500, False)), 500
    finally:
        conn.close()

@food_trade_api.route("/weekly_products", methods=["POST"])
@jwt_required()
def create_weekly_product():
    user_id = get_authenticated_user_id()
    if not check_admin(user_id):
        return jsonify(envelope(None, "Unauthorized", 403, False)), 403
        
    data = request.get_json() or {}
    name = str(data.get("name") or "").strip()
    description = str(data.get("description") or "").strip()
    price = data.get("price")
    image_url = str(data.get("image_url") or "").strip()
    status = str(data.get("status") or "inactive").strip().lower()
    
    if not name or price is None:
        return jsonify(envelope(None, "name and price are required", 400, False)), 400
        
    if status not in ("active", "inactive"):
        status = "inactive"

    conn, cursor = db_connection()
    try:
        cursor.execute(
            """
            INSERT INTO food_trade_weekly_products (
                name, description, price, image_url, status
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (name, description, float(price), image_url, status)
        )
        product_id = cursor.lastrowid
        conn.commit()
        return jsonify(envelope({"id": product_id}, "Product created successfully.", 201)), 201
    except Exception as exc:
        conn.rollback()
        return jsonify(envelope(None, "Internal server error", 500, False)), 500
    finally:
        conn.close()

@food_trade_api.route("/weekly_products/<int:product_id>", methods=["PUT"])
@jwt_required()
def update_weekly_product(product_id):
    user_id = get_authenticated_user_id()
    if not check_admin(user_id):
        return jsonify(envelope(None, "Unauthorized", 403, False)), 403
        
    data = request.get_json() or {}
    name = str(data.get("name") or "").strip()
    description = str(data.get("description") or "").strip()
    price = data.get("price")
    image_url = str(data.get("image_url") or "").strip()
    status = str(data.get("status") or "").strip().lower()

    conn, cursor = db_connection()
    try:
        cursor.execute("SELECT id FROM food_trade_weekly_products WHERE id = ?", (product_id,))
        if not cursor.fetchone():
            return jsonify(envelope(None, "Product not found", 404, False)), 404
            
        update_fields = []
        params = []
        if name:
            update_fields.append("name = ?")
            params.append(name)
        if description:
            update_fields.append("description = ?")
            params.append(description)
        if price is not None:
            update_fields.append("price = ?")
            params.append(float(price))
        if image_url:
            update_fields.append("image_url = ?")
            params.append(image_url)
        if status in ("active", "inactive"):
            update_fields.append("status = ?")
            params.append(status)
            
        if not update_fields:
            return jsonify(envelope(None, "No valid fields to update", 400, False)), 400
            
        update_fields.append("updated_at = CURRENT_TIMESTAMP")
        params.append(product_id)
        
        query = f"UPDATE food_trade_weekly_products SET {', '.join(update_fields)} WHERE id = ?"
        cursor.execute(query, tuple(params))
        conn.commit()
        
        return jsonify(envelope(None, "Product updated successfully.", 200)), 200
    except Exception as exc:
        conn.rollback()
        return jsonify(envelope(None, "Internal server error", 500, False)), 500
    finally:
        conn.close()

@food_trade_api.route("/weekly_products/<int:product_id>", methods=["DELETE"])
@jwt_required()
def delete_weekly_product(product_id):
    user_id = get_authenticated_user_id()
    if not check_admin(user_id):
        return jsonify(envelope(None, "Unauthorized", 403, False)), 403

    conn, cursor = db_connection()
    try:
        cursor.execute("SELECT id FROM food_trade_weekly_products WHERE id = ?", (product_id,))
        if not cursor.fetchone():
            return jsonify(envelope(None, "Product not found", 404, False)), 404

        cursor.execute("DELETE FROM food_trade_weekly_products WHERE id = ?", (product_id,))
        conn.commit()
        return jsonify(envelope(None, "Product deleted successfully.", 200)), 200
    except Exception as exc:
        conn.rollback()
        return jsonify(envelope(None, "Internal server error", 500, False)), 500
    finally:
        conn.close()
