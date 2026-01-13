from flask import Blueprint, request, jsonify
from flask_cors import CORS
from flask_jwt_extended import get_jwt_identity, jwt_required
from database import db_connection
from routes import response

# Initialize Blueprint
carts = Blueprint('carts', __name__)


# ADD ITEM TO CART
@carts.route('/', methods=['POST'])
@jwt_required()
def add_to_cart():
    try:
        user_id = get_jwt_identity()
        data = request.get_json()

        if not data or 'product_id' not in data or 'quantity' not in data:
            return jsonify(response([], "Missing product_id or quantity", 400)), 400

        product_id = data['product_id']
        quantity = data['quantity']

        conn, cursor = db_connection()

        # Check if product exists
        cursor.execute('SELECT * FROM Products WHERE id = ?', (product_id,))
        product = cursor.fetchone()
        if not product:
            return jsonify(response([], "Product not found", 404)), 404

        # Check if already in cart
        cursor.execute(
            'SELECT * FROM Cart WHERE user_id = ? AND product_id = ?',
            (user_id, product_id)
        )
        existing = cursor.fetchone()

        if existing:
            cursor.execute(
                'UPDATE Cart SET quantity = quantity + ? WHERE user_id = ? AND product_id = ?',
                (quantity, user_id, product_id)
            )
        else:
            cursor.execute(
                'INSERT INTO Cart (user_id, product_id, quantity) VALUES (?, ?, ?)',
                (user_id, product_id, quantity)
            )

        conn.commit()

        # Get the latest cart item
        cursor.execute('''
            SELECT Cart.id, Cart.product_id, Cart.quantity, 
                   Products.title, Products.price, Products.image_url
            FROM Cart
            JOIN Products ON Cart.product_id = Products.id
            WHERE Cart.user_id = ? AND Cart.product_id = ?
        ''', (user_id, product_id))
        cart_item = cursor.fetchone()

        conn.close()

        data = {
            "id": cart_item[0],
            "product_id": cart_item[1],
            "quantity": cart_item[2],
            "title": cart_item[3],
            "price": cart_item[4],
            "image_url": cart_item[5],
        }

        return jsonify(response(data, "Item added to cart", 201)), 201

    except Exception as e:
        return jsonify(response([], f"Error: {str(e)}", 500)), 500


# GET USER CART 
@carts.route('/', methods=['GET'])
@jwt_required()
def get_carts():
    try:
        user_id = get_jwt_identity()
        conn, cursor = db_connection()

        cursor.execute('''
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
        ''', (user_id,))

        rows = cursor.fetchall()
        carts = []

        for row in rows:
            item = dict(row)
            item['totalPrice'] = item['price'] * item['quantity']
            carts.append(item)

        conn.close()
        return jsonify(response(carts, "Successfully retrieved cart items.", 200)), 200

    except Exception as e:
        return jsonify(response([], f"Error: {str(e)}", 500)), 500



@carts.route('/<int:cart_id>', methods=['PUT'])
@jwt_required()
def update_cart_item(cart_id):
    try:
        user_id = get_jwt_identity()
        data = request.get_json()

        if not data or 'quantity' not in data:
            return jsonify(response([], "Missing quantity", 400)), 400

        quantity = data['quantity']
        if quantity <= 0:
            return jsonify(response([], "Quantity must be greater than 0", 400)), 400

        conn, cursor = db_connection()

        # Check if the cart item exists and belongs to the user
        cursor.execute('SELECT * FROM Cart WHERE id = ? AND user_id = ?', (cart_id, user_id))
        item = cursor.fetchone()
        if not item:
            conn.close()
            return jsonify(response([], "Cart item not found", 404)), 404

        # Update the quantity
        cursor.execute(
            'UPDATE Cart SET quantity = ? WHERE id = ? AND user_id = ?',
            (quantity, cart_id, user_id)
        )
        conn.commit()

        # Fetch updated item with product info
        cursor.execute('''
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
        ''', (cart_id, user_id))
        updated_item = cursor.fetchone()

        conn.close()

        if not updated_item:
            return jsonify(response([], "Updated cart item not found", 404)), 404

        # Build response
        updated_data = dict(updated_item)
        updated_data["totalPrice"] = updated_data["price"] * updated_data["quantity"]

        return jsonify(response(updated_data, "Cart item updated", 200)), 200

    except Exception as e:
        return jsonify(response([], f"Error: {str(e)}", 500)), 500



@carts.route('/<int:cart_id>', methods=['DELETE'])
@jwt_required()
def delete_cart_item(cart_id):
    try:
        user_id = get_jwt_identity()
        conn, cursor = db_connection()

        # Check if the cart item belongs to the user
        cursor.execute(
            'SELECT 1 FROM Cart WHERE id = ? AND user_id = ?',
            (cart_id, user_id)
        )
        if not cursor.fetchone():
            conn.close()
            return jsonify(response([], "Cart item not found", 404)), 404

        # Delete the item
        cursor.execute('DELETE FROM Cart WHERE id = ? AND user_id = ?', (cart_id, user_id))

        conn.commit()
        conn.close()
        return jsonify(response([], "Cart item deleted", 200)), 200

    except Exception as e:
        return jsonify(response([], f"Error: {str(e)}", 500)), 500


@carts.route('/clear', methods=['DELETE'])
@jwt_required()
def clear_cart():
    try:
        user_id = get_jwt_identity()
        conn, cursor = db_connection()
        cursor.execute('DELETE FROM Cart WHERE user_id = ?', (user_id,))
        conn.commit()
        conn.close()
        return jsonify(response([], "All cart items cleared", 200)), 200
    except Exception as e:
        return jsonify(response([], f"Error: {str(e)}", 500)), 500
