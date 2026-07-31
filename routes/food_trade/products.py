from flask import jsonify, request
from flask_jwt_extended import jwt_required

from database.connection import db_connection
from middleware.authMiddleware import get_authenticated_user_id
from routes.api_envelope import envelope
from . import food_trade_api
from .utils import check_admin


@food_trade_api.route("/products", methods=["GET"])
def list_products():
    category = request.args.get("category")
    q = request.args.get("q")
    
    query = """
        SELECT p.id, p.name, p.slug, p.description, p.price_ghs, p.unit, 
               p.min_order_qty, p.stock_qty, p.image_url, p.category_id,
               c.name as category_name, c.slug as category_slug
        FROM food_trade_products p
        LEFT JOIN food_trade_categories c ON p.category_id = c.id
        WHERE p.is_active = 1
    """
    params = []
    
    if category:
        query += " AND c.slug = ?"
        params.append(category)
        
    if q and q.strip():
        query += " AND p.name LIKE ?"
        params.append(f"%{q.strip()}%")
        
    query += " ORDER BY p.name ASC"
    
    conn, cursor = db_connection()
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    products = []
    for row in rows:
        prod = dict(row)
        if prod.get("category_id"):
            prod["categories"] = {
                "name": prod.pop("category_name", None),
                "slug": prod.pop("category_slug", None)
            }
        products.append(prod)
        
    return jsonify(envelope(products, "Products retrieved successfully", 200, True)), 200


@food_trade_api.route("/products/<slug>", methods=["GET"])
def get_product_by_slug(slug):
    conn, cursor = db_connection()
    cursor.execute("""
        SELECT p.id, p.name, p.slug, p.description, p.price_ghs, p.unit, p.image_url,
               p.min_order_qty, p.stock_qty, p.image_url, p.category_id,
               c.name as category_name, c.slug as category_slug
        FROM food_trade_products p
        LEFT JOIN food_trade_categories c ON p.category_id = c.id
        WHERE p.slug = ? AND p.is_active = 1
    """, (slug,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return jsonify(envelope(None, "Product not found", 404, False)), 404
        
    prod = dict(row)
    if prod.get("category_id"):
        prod["categories"] = {
            "name": prod.pop("category_name", None),
            "slug": prod.pop("category_slug", None)
        }
    return jsonify(envelope(prod, "Product retrieved successfully", 200, True)), 200


@food_trade_api.route("/admin/products", methods=["GET"])
@jwt_required()
def admin_list_products():
    user_id = get_authenticated_user_id()
    if not check_admin(user_id):
        return jsonify(envelope(None, "Forbidden: admin only", 403, False)), 403
        
    conn, cursor = db_connection()
    cursor.execute("""
        SELECT id, name, slug, description, price_ghs, unit, 
               min_order_qty, stock_qty, is_active, category_id, image_url
        FROM food_trade_products ORDER BY name ASC
    """)
    rows = cursor.fetchall()
    conn.close()
    return jsonify(envelope([dict(r) for r in rows], "Admin products", 200, True)), 200


@food_trade_api.route("/admin/products", methods=["POST"])
@jwt_required()
def admin_upsert_product():
    user_id = get_authenticated_user_id()
    if not check_admin(user_id):
        return jsonify(envelope(None, "Forbidden: admin only", 403, False)), 403
        
    data = request.json
    conn, cursor = db_connection()
    
    if data.get("id"):
        # Update
        cursor.execute("""
            UPDATE food_trade_products SET
                name=?, slug=?, description=?, price_ghs=?, unit=?, image_url=?, 
                min_order_qty=?, stock_qty=?, is_active=?, category_id=?, updated_at=CURRENT_TIMESTAMP
            WHERE id=?
        """, (data.get("name"), data.get("slug"), data.get("description", ""), 
              data.get("price_ghs"), data.get("unit"), data.get("image_url"), data.get("min_order_qty"), 
              data.get("stock_qty"), data.get("is_active", True), data.get("category_id"), data.get("id")))
    else:
        # Insert
        cursor.execute("""
            INSERT INTO food_trade_products (name, slug, description, price_ghs, unit, image_url, min_order_qty, stock_qty, is_active, category_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (data.get("name"), data.get("slug"), data.get("description", ""), 
              data.get("price_ghs"), data.get("unit"), data.get("image_url"), data.get("min_order_qty"), 
              data.get("stock_qty"), data.get("is_active", True), data.get("category_id")))
              
    conn.commit()
    conn.close()
    return jsonify(envelope({"ok": True}, "Product upserted", 200, True)), 200


@food_trade_api.route("/admin/products/<int:pid>", methods=["DELETE"])
@jwt_required()
def admin_delete_product(pid):
    user_id = get_authenticated_user_id()
    if not check_admin(user_id):
        return jsonify(envelope(None, "Forbidden: admin only", 403, False)), 403
        
    conn, cursor = db_connection()
    cursor.execute("DELETE FROM food_trade_products WHERE id = ?", (pid,))
    conn.commit()
    conn.close()
    return jsonify(envelope({"ok": True}, "Product deleted", 200, True)), 200
