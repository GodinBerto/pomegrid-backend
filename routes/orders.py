from flask import Blueprint, request, jsonify
from flask_cors import CORS
from flask_jwt_extended import get_jwt_identity, jwt_required
from database import db_connection
from routes import response

# Initialize the Flask auth
orders = Blueprint('orders', __name__)

@orders.route('/', methods=['GET'])
def get_orders():
    try:
        conn, cursor = db_connection()
        cursor.execute('SELECT * FROM Orders')
        rows = cursor.fetchall()
        orders = [dict(row) for row in rows]        
        conn.close()
        return jsonify(response(orders, "Successfully retrieved orders.", 200)), 200

    except Exception as e:
        # print("Error fetching orders:", e)
        return jsonify(response( [],f"Error: {e}", 500)), 500


@orders.route('/<int:order_id>', methods=['GET'])
@jwt_required()
def get_order(order_id):
    try:
        conn, cursor = db_connection()
        cursor.execute('SELECT * FROM Orders WHERE id = ?', (order_id,))
        order = cursor.fetchone()
        if not order:
            return jsonify(response([], "Order not found.", 404)), 404
        
        order_items = []
        cursor.execute('SELECT * FROM OrderItems WHERE order_id = ?', (order_id,))
        items = cursor.fetchall()
        for item in items:
            order_items.append(dict(item))
        
        order_data = dict(order)
        order_data['items'] = order_items
        
        conn.close()
        return jsonify(response(order_data, "Successfully retrieved order.", 200)), 200

    except Exception as e:
        # print("Error fetching order:", e)
        return jsonify(response([], f"Error: {e}", 500)), 500
        
    
@orders.route('/get-user-orders', methods=['GET'])
@jwt_required()
def get_user_orders():
    try:
        user_id = get_jwt_identity()
        conn, cursor = db_connection()
        cursor.execute('SELECT * FROM Orders WHERE user_id = ?', (user_id,))
        rows = cursor.fetchall()
        orders = [dict(row) for row in rows]
        
        for order in orders:
            cursor.execute('SELECT * FROM OrderItems WHERE order_id = ?', (order['id'],))
            items = cursor.fetchall()
            order['items'] = [dict(item) for item in items]
        
        conn.close()
        return jsonify(response(orders, "Successfully retrieved users's orders.", 200)), 200

    except Exception as e:
        # print("Error fetching farmer's orders:", e)
        return jsonify(response([], f"Error: {e}", 500)), 500
    

@orders.route('/create-order', methods=['POST'])
@jwt_required()
def create_order():
    try:
        user_id = get_jwt_identity()
        data = request.get_json()

        # Validate input
        if not data or 'items' not in data or not isinstance(data['items'], list) or not data['items']:
            return jsonify(response([], "Invalid order data.", 400)), 400

        conn, cursor = db_connection()

        # Extract product IDs from input items
        product_ids = tuple(item['product_id'] for item in data['items'])

        # Fetch valid product IDs from the database
        query = f"SELECT id FROM Products WHERE id IN ({','.join('?' for _ in product_ids)})"
        cursor.execute(query, product_ids)
        existing_ids = set(row['id'] for row in cursor.fetchall())

        # Validate if all products exist
        missing_ids = [pid for pid in product_ids if pid not in existing_ids]
        if missing_ids:
            return jsonify(response([], f"Product(s) not found: {missing_ids}", 404)), 404

        # Calculate total price
        total_price = sum(item['unit_price'] * item['quantity'] for item in data['items'])

        # Create order
        cursor.execute('''
            INSERT INTO Orders (user_id, total_price, status)
            VALUES (?, ?, ?)
        ''', (user_id, total_price, 'pending'))
        order_id = cursor.lastrowid

        # Insert items into OrderItems
        for item in data['items']:
            cursor.execute('''
                INSERT INTO OrderItems (order_id, user_id, product_id, name, quantity, unit_price)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                order_id,
                user_id,
                item['product_id'],
                item.get('name', ''),
                item['quantity'],
                item['unit_price']
            ))

        conn.commit()
        conn.close()

        return jsonify(response({"order_id": order_id}, "Order created successfully.", 201)), 201

    except Exception as e:
        return jsonify(response([], f"Error: {str(e)}", 500)), 500


@orders.route('/<int:order_id>/update', methods=['PUT'])
@jwt_required()
def update_order(order_id):
    try:
        user_id = get_jwt_identity()
        data = request.get_json()

        if 'status' not in data:
            return jsonify(response([], "Status is required", 400)), 400

        conn, cursor = db_connection()

        # Optional: check if order belongs to user
        cursor.execute('SELECT * FROM Orders WHERE id = ? AND user_id = ?', (order_id, user_id))
        order = cursor.fetchone()
        if not order:
            return jsonify(response([], "Order not found or unauthorized", 404)), 404

        cursor.execute('''
            UPDATE Orders SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?
        ''', (data['status'], order_id))

        conn.commit()
        conn.close()

        return jsonify(response([], "Order updated successfully", 200)), 200

    except Exception as e:
        return jsonify(response([], f"Error: {e}", 500)), 500


@orders.route('/<int:order_id>/delete', methods=['DELETE'])
@jwt_required()
def delete_order(order_id):
    try:
        user_id = get_jwt_identity()
        conn, cursor = db_connection()

        # Check if order exists and belongs to user
        cursor.execute('SELECT * FROM Orders WHERE id = ? AND user_id = ?', (order_id, user_id))
        order = cursor.fetchone()
        if not order:
            return jsonify(response([], "Order not found or unauthorized", 404)), 404

        # Only allow delete if status is 'pending'
        if order['status'] != 'pending':
            return jsonify(response([], "Only pending orders can be deleted", 403)), 403

        # Delete order items first
        cursor.execute('DELETE FROM OrderItems WHERE order_id = ?', (order_id,))
        cursor.execute('DELETE FROM Orders WHERE id = ?', (order_id,))

        conn.commit()
        conn.close()

        return jsonify(response([], "Order deleted successfully", 200)), 200

    except Exception as e:
        return jsonify(response([], f"Error: {e}", 500)), 500


@orders.route('/get-farmer-orders', methods=['GET'])
@jwt_required()
def get_farmer_orders():
    conn, cursor = None, None
    try:
        user_id = get_jwt_identity()
        conn, cursor = db_connection()
        
        # Check if the user is a farmer
        cursor.execute('SELECT * FROM Users WHERE id = ? AND user_type = ?', (user_id, 'farmer'))
        farmer = cursor.fetchone()
        if not farmer:
            return jsonify(response([], "User is not a registered farmer", 404)), 404

        # Get orders that include products owned by this farmer
        cursor.execute('''
            SELECT DISTINCT o.*
            FROM Orders o
            JOIN OrderItems oi ON o.id = oi.order_id
            JOIN Products p ON oi.product_id = p.id
            WHERE p.user_id = ?
            ORDER BY o.created_at DESC
        ''', (user_id,))
        rows = cursor.fetchall()
        orders = [dict(row) for row in rows]

        # For each order, fetch the items belonging to the farmer
        for order in orders:
            cursor.execute('''
                SELECT oi.*
                FROM OrderItems oi
                JOIN Products p ON oi.product_id = p.id
                WHERE oi.order_id = ? AND p.user_id = ?
            ''', (order['id'], user_id))
            items = cursor.fetchall()
            order['items'] = [dict(item) for item in items]

        return jsonify(response(orders, "Successfully retrieved orders made to the farmer.", 200)), 200

    except Exception as e:
        return jsonify(response([], f"Error: {str(e)}", 500)), 500

    finally:
        if conn:
            conn.close()

