from flask import Blueprint, request, jsonify
from flask_cors import CORS
from flask_jwt_extended import get_jwt_identity, jwt_required
from database import db_connection
from routes import response

# Initialize the Flask auth
products = Blueprint('products', __name__)

@products.route('/', methods=['GET'])
@jwt_required()
def get_products():
    try:
        conn, cursor = db_connection()
        cursor.execute('SELECT * FROM Products')
        rows = cursor.fetchall()
        products = [dict(row) for row in rows]        
        conn.close()
        return jsonify(response(products, "Successfully retrieved products.", 200)), 200

    except Exception as e:
        # print("Error fetching products:", e)
        return jsonify(response( [],f"Error: {e}", 500)), 500
    

@products.route('/<int:product_id>', methods=['GET'])
@jwt_required()
def get_product(product_id):
    try:
        conn, cursor = db_connection()
        cursor.execute('SELECT * FROM Products WHERE id = ?', (product_id,))
        row = cursor.fetchone()
        if row:
            product = dict(row)
            conn.close()
            return jsonify(response(product, "Successfully retrieved product.", 200)), 200
        else:
            conn.close()
            return jsonify(response(None, "Product not found", 404)), 404

    except Exception as e:
        return jsonify(response(None, f"Error: {e}", 500)), 500
    

# Product types GET endpoint
@products.route('/types', methods=['GET'])
@jwt_required()
def get_product_types():
    try:
        conn, cursor = db_connection()
        cursor.execute('SELECT * FROM ProductTypes')
        rows = cursor.fetchall()
        product_types = [dict(row) for row in rows]
        conn.close()
        return jsonify(response(product_types, "Successfully retrieved product types.", 200)), 200

    except Exception as e:
        return jsonify(response([], f"Error: {e}", 500)), 500
    
    
# Product types POST endpoint
@products.route('/types', methods=['POST'])
@jwt_required()
def add_product_type():
    data = request.get_json()
    current_user = get_jwt_identity()
    category_id = data.get('category_id')
    name = data.get('name')
    description = data.get('description', '')
    # Validate required fields
    if not all([category_id, name]):
        return jsonify(response(None, "Missing required fields", 400)), 400
    
    # Check if the category exists
    try:
        conn, cursor = db_connection()
        cursor.execute('SELECT id FROM Categories WHERE id = ?', (category_id,))
        category = cursor.fetchone()
        if not category:
            conn.close()
            return jsonify(response(None, "Category not found", 404)), 404
        conn.close()
    except Exception as e:
        return jsonify(response(None, f"Error checking category: {e}", 500)), 500
    
    try:
        conn, cursor = db_connection()
        cursor.execute('''
            INSERT INTO ProductTypes (category_id, name, description)
            VALUES (?, ?, ?)
        ''', (category_id, name, description))
        product_type_id = cursor.lastrowid  # Get ID before closing
        conn.commit()
        conn.close()
        
        data = {
            'id': product_type_id,
            'category_id': category_id,
            'name': name,
            'description': description
        }
        
        return jsonify(response(data, "Product type added successfully", 201)), 201
    except Exception as e:
        return jsonify(response(None, f"Error: {e}", 500)), 500


@products.route('/', methods=['POST'])
@jwt_required()
def add_product():
    data = request.get_json()
    current_user = get_jwt_identity()  # Assuming this is user_id

    title = data.get('title')
    type_id = data.get('type_id')
    description = data.get('description', '')
    price = data.get('price')
    quantity = data.get('quantity')
    is_alive = data.get('is_live', False)
    is_fresh = data.get('is_fresh', True)
    image_url = data.get('image_url', None)

    # Validate required fields
    if not all([title, type_id, price, quantity, image_url]):
        return jsonify(response(None, "Missing required fields", 400)), 400
    
    try: 
        conn, cursor = db_connection()
        cursor.execute('SELECT * FROM ProductTypes WHERE id = ?', (type_id))
        product_type = cursor.fetchone()
        if not product_type:
            return jsonify(response(None, "Product not found", 404))
        conn.close()
    
    except Exception as e:
        return jsonify(response(None, "Error fetching product type", 500))

    try:
        conn, cursor = db_connection()
        if is_alive:     
            cursor.execute('''
                INSERT INTO Products (farmer_id, type_id, title, description, price, quantity, is_alive, image_url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (current_user, type_id, title, description, price, quantity, is_alive, image_url))
        elif is_fresh:
            cursor.execute('''
                INSERT INTO Products (farmer_id, type_id, title, description, price, quantity, is_fresh, image_url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (current_user, type_id, title, description, price, quantity, is_fresh, image_url))
        product_id = cursor.lastrowid  # Get ID before closing
        conn.commit()
        conn.close()
        
        if is_alive:
            data = {
            'id': product_id,
            'title': title,
            'type_id': type_id,
            'description': description,
            'price': price,
            'quantity': quantity,
            'is_live': is_alive,
            'image_url': image_url
        }
        else:
            data = {
            'id': product_id,
            'title': title,
            'type_id': type_id,
            'description': description,
            'price': price,
            'quantity': quantity,
            'is_fresh': is_fresh,
            'image_url': image_url
        }

        
        return jsonify(response(data, "Product added successfully", 201)), 201

    except Exception as e:
        return jsonify(response(None, f"Error: {e}", 500)), 500

@products.route('/<int:product_id>', methods=['PUT'])
@jwt_required()
def update_product(product_id):
    data = request.get_json()
    current_user = get_jwt_identity()
    title = data.get('title')
    type_id = data.get('type_id')
    description = data.get('description', '')
    price = data.get('price')
    quantity = data.get('quantity')
    is_alive = data.get('is_alive', False)
    is_fresh = data.get('is_fresh', True)
    image_url = data.get('image_url', None)
    # Validate required fields
    if not all([title, type_id, price, quantity, image_url]):
        return jsonify(response(None, "Missing required fields", 400)), 400
    try:
        conn, cursor = db_connection()
        if is_alive:
            cursor.execute('''
                UPDATE Products
                SET title = ?, type_id = ?, description = ?, price = ?, quantity = ?, is_alive = ?, image_url = ?
                WHERE id = ? AND farmer_id = ?
            ''', (title, type_id, description, price, quantity, is_alive, image_url, product_id, current_user))
        elif is_fresh:
            cursor.execute('''
                UPDATE Products
                SET title = ?, type_id = ?, description = ?, price = ?, quantity = ?, is_fresh = ?, image_url = ?
                WHERE id = ? AND farmer_id = ?
            ''', (title, type_id, description, price, quantity, is_fresh, image_url, product_id, current_user))
        
        conn.commit()
        if cursor.rowcount == 0:
            conn.close()
            return jsonify(response(None, "Product not found or not authorized", 404)), 404
        
        conn.close()
        
        if is_alive:
            data = {
                'id': product_id,
                'title': title,
                'type_id': type_id,
                'description': description,
                'price': price,
                'quantity': quantity,
                'is_alive': is_alive,
                'image_url': image_url
            }
        else:
            data = {
                'id': product_id,
                'title': title,
                'type_id': type_id,
                'description': description,
                'price': price,
                'quantity': quantity,
                'is_fresh': is_fresh,
                'image_url': image_url
            }
        
        return jsonify(response(data, "Product updated successfully", 200)), 200
    except Exception as e:
        return jsonify(response(None, f"Error: {e}", 500)), 500
    

@products.route('/<int:product_id>', methods=['DELETE'])
@jwt_required()
def delete_product(product_id):
    current_user = get_jwt_identity()
    try:
        conn, cursor = db_connection()
        cursor.execute('DELETE FROM Products WHERE id = ? AND farmer_id = ?', (product_id, current_user))
        conn.commit()
        
        if cursor.rowcount == 0:
            conn.close()
            return jsonify(response(None, "Product not found or not authorized", 404)), 404
        
        conn.close()
        return jsonify(response(None, "Product deleted successfully", 200)), 200

    except Exception as e:
        return jsonify(response(None, f"Error: {e}", 500)), 500
    
@products.route('/<int:product_id>/image', methods=['POST'])
@jwt_required()
def upload_product_image(product_id):
    current_user = get_jwt_identity()
    if 'image' not in request.files:
        return jsonify(response(None, "No image file provided", 400)), 400

    image_file = request.files['image']
    if image_file.filename == '':
        return jsonify(response(None, "No selected file", 400)), 400

    try:
        # Save the image file
        image_url = f"/images/products/{product_id}/{image_file.filename}"
        image_file.save(f"./static{image_url}")

        # Update the product with the new image URL
        conn, cursor = db_connection()
        cursor.execute('UPDATE Products SET image_url = ? WHERE id = ? AND farmer_id = ?', (image_url, product_id, current_user))
        conn.commit()

        if cursor.rowcount == 0:
            conn.close()
            return jsonify(response(None, "Product not found or not authorized", 404)), 404

        conn.close()
        return jsonify(response({'image_url': image_url}, "Image uploaded successfully", 200)), 200

    except Exception as e:
        return jsonify(response(None, f"Error: {e}", 500)), 500
    

@products.route('/<int:product_id>/image', methods=['GET'])
@jwt_required()
def get_product_image(product_id):
    try:
        conn, cursor = db_connection()
        cursor.execute('SELECT image_url FROM Products WHERE id = ?', (product_id,))
        row = cursor.fetchone()
        if row and row['image_url']:
            image_url = row['image_url']
            conn.close()
            return jsonify(response({'image_url': image_url}, "Image retrieved successfully", 200)), 200
        else:
            conn.close()
            return jsonify(response(None, "Image not found", 404)), 404

    except Exception as e:
        return jsonify(response(None, f"Error: {e}", 500)), 500
    

@products.route('/<int:product_id>/image', methods=['DELETE'])
@jwt_required()
def delete_product_image(product_id):
    current_user = get_jwt_identity()
    try:
        conn, cursor = db_connection()
        cursor.execute('SELECT image_url FROM Products WHERE id = ? AND farmer_id = ?', (product_id, current_user))
        row = cursor.fetchone()
        
        if not row or not row['image_url']:
            conn.close()
            return jsonify(response(None, "Image not found or not authorized", 404)), 404
        
        image_url = row['image_url']
        cursor.execute('UPDATE Products SET image_url = NULL WHERE id = ? AND farmer_id = ?', (product_id, current_user))
        conn.commit()
        
        # Optionally delete the image file from the server
        # os.remove(f"./static{image_url}")

        conn.close()
        return jsonify(response(None, "Image deleted successfully", 200)), 200

    except Exception as e:
        return jsonify(response(None, f"Error: {e}", 500)), 500
    
