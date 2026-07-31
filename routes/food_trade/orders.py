import threading
from flask import jsonify, request
from flask_jwt_extended import jwt_required

from database.connection import db_connection
from middleware.authMiddleware import get_authenticated_user_id
from routes.api_envelope import envelope
from . import food_trade_api
from .utils import check_admin, update_product_stock


@food_trade_api.route("/orders", methods=["POST"])
@jwt_required()
def place_order():
    user_id = get_authenticated_user_id()
    if not user_id:
        return jsonify(envelope(None, "Unauthorized", 401, False)), 401
        
    data = request.json
    if not data or not data.get("items"):
        return jsonify(envelope(None, "Items are required", 400, False)), 400
        
    contact_phone = data.get("contact_phone", "")
    delivery_region = data.get("delivery_region", "")
    delivery_address = data.get("delivery_address", "")
    notes = data.get("notes", "")
    items = data.get("items", [])
    
    product_ids = [item.get("product_id") for item in items if item.get("product_id")]
    if not product_ids:
        return jsonify(envelope(None, "Invalid items", 400, False)), 400
        
    payment_reference = data.get("payment_reference")
    
    if not payment_reference:
        return jsonify(envelope(None, "payment_reference is required", 400, False)), 400
        
    conn, cursor = db_connection()
    try:
        # Verify payment
        cursor.execute("SELECT id, status, user_id FROM food_trade_payments WHERE reference = ?", (payment_reference,))
        payment = cursor.fetchone()
        if not payment:
            return jsonify(envelope(None, "Payment reference not found", 400, False)), 400
        if payment["status"] != "success":
            return jsonify(envelope(None, "Payment was not successful", 400, False)), 400
        if payment["user_id"] != user_id:
            return jsonify(envelope(None, "Payment does not belong to this user", 403, False)), 403
            
        # Check if already used
        cursor.execute("SELECT id FROM food_trade_orders WHERE payment_reference = ?", (payment_reference,))
        if cursor.fetchone():
            return jsonify(envelope(None, "Payment reference already used for an order", 400, False)), 400

        # Check products
        placeholders = ",".join(["?"] * len(product_ids))
        cursor.execute(f"SELECT id, name, price_ghs, is_active FROM food_trade_products WHERE id IN ({placeholders})", product_ids)
        products_db = cursor.fetchall()
        
        prod_map = {str(p["id"]): p for p in products_db}
        
        total = 0
        order_rows = []
        
        for item in items:
            pid = str(item.get("product_id"))
            qty = int(item.get("qty", 1))
            
            p = prod_map.get(pid)
            if not p or not p["is_active"]:
                return jsonify(envelope(None, f"Product {pid} unavailable", 400, False)), 400
                
            unit_price = float(p["price_ghs"])
            line_total = unit_price * qty
            total += line_total
            
            order_rows.append({
                "product_id": p["id"],
                "product_name": p["name"],
                "qty": qty,
                "unit_price_ghs": unit_price
            })
            
        # Create order
        cursor.execute("""
            INSERT INTO food_trade_orders (user_id, contact_phone, delivery_region, delivery_address, notes, total_ghs, status, payment_reference)
            VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
        """, (user_id, contact_phone, delivery_region, delivery_address, notes, total, payment_reference))
        order_id = cursor.lastrowid
        
        # Create order items
        for row in order_rows:
            cursor.execute("""
                INSERT INTO food_trade_order_items (order_id, product_id, product_name, qty, unit_price_ghs)
                VALUES (?, ?, ?, ?, ?)
            """, (order_id, row["product_id"], row["product_name"], row["qty"], row["unit_price_ghs"]))
            
            # Async stock update
            threading.Thread(target=update_product_stock, args=(row["product_id"], row["qty"])).start()
            
        # Clear the user's cart
        cursor.execute("DELETE FROM food_trade_carts WHERE user_id = ?", (user_id,))
            
        conn.commit()
        return jsonify(envelope({"orderId": order_id, "total": total}, "Order placed successfully", 201, True)), 201
    except Exception as exc:
        conn.rollback()
        return jsonify(envelope(None, str(exc), 500, False)), 500
    finally:
        conn.close()


@food_trade_api.route("/orders/me", methods=["GET"])
@jwt_required()
def get_my_orders():
    user_id = get_authenticated_user_id()
    if not user_id:
        return jsonify(envelope(None, "Unauthorized", 401, False)), 401
        
    conn, cursor = db_connection()
    cursor.execute("""
        SELECT id, status, total_ghs, created_at, delivery_region 
        FROM food_trade_orders 
        WHERE user_id = ? ORDER BY created_at DESC
    """, (user_id,))
    orders_rows = cursor.fetchall()
    
    orders = []
    for ord_row in orders_rows:
        o = dict(ord_row)
        cursor.execute("SELECT id, product_name, qty, unit_price_ghs FROM food_trade_order_items WHERE order_id = ?", (o["id"],))
        o["order_items"] = [dict(i) for i in cursor.fetchall()]
        orders.append(o)
        
    conn.close()
    return jsonify(envelope(orders, "Orders retrieved successfully", 200, True)), 200


@food_trade_api.route("/admin/orders", methods=["GET"])
@jwt_required()
def admin_list_orders():
    user_id = get_authenticated_user_id()
    if not check_admin(user_id):
        return jsonify(envelope(None, "Forbidden: admin only", 403, False)), 403
        
    conn, cursor = db_connection()
    cursor.execute("""
        SELECT id, user_id, status, total_ghs, contact_phone, 
               delivery_region, delivery_address, notes, created_at
        FROM food_trade_orders ORDER BY created_at DESC
    """)
    orders_rows = cursor.fetchall()
    
    orders = []
    for ord_row in orders_rows:
        o = dict(ord_row)
        cursor.execute("SELECT id, product_name, qty, unit_price_ghs FROM food_trade_order_items WHERE order_id = ?", (o["id"],))
        o["order_items"] = [dict(i) for i in cursor.fetchall()]
        orders.append(o)
        
    conn.close()
    return jsonify(envelope(orders, "Admin orders", 200, True)), 200


@food_trade_api.route("/admin/orders/status", methods=["POST"])
@jwt_required()
def admin_update_order_status():
    user_id = get_authenticated_user_id()
    if not check_admin(user_id):
        return jsonify(envelope(None, "Forbidden: admin only", 403, False)), 403
        
    data = request.json
    order_id = data.get("id")
    status = data.get("status")
    
    if not order_id or status not in ["pending", "confirmed", "shipped", "delivered", "cancelled"]:
        return jsonify(envelope(None, "Invalid data", 400, False)), 400
        
    conn, cursor = db_connection()
    cursor.execute("UPDATE food_trade_orders SET status = ? WHERE id = ?", (status, order_id))
    conn.commit()
    conn.close()
    return jsonify(envelope({"ok": True}, "Order status updated", 200, True)), 200
