import cloudinary
from flask import Blueprint, request, jsonify
from flask_cors import CORS
from flask_jwt_extended import get_jwt_identity, jwt_required
from database import db_connection
from routes import response
from datetime import datetime, timedelta

# Initialize the Flask auth
products = Blueprint('products', __name__)

@products.route('/', methods=['GET'])
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


@products.route('/', methods=['POST'])
@jwt_required()
def add_product():
    data = request.get_json()
    current_user = get_jwt_identity()  # Assuming this is user_id
    
    title = data.get('title')
    category = data.get('category')
    animal_type = data.get('animal_type')
    description = request.form.get('description', '')
    price = data.get('price')
    quantity = data.get('quantity')
    is_alive = data.get('is_live', 'false')
    is_fresh = data.get('is_fresh', 'true')
    rating = float(data.get('rating', 4.0))
    discount_percentage = data.get('discount_percentage')
    weight_per_unit = float(data.get('weight_per_unit', 1.0))
    animal_stage = data.get('animal_stage', None)

    # Get the image file
    image_url = data.get('image_url')

    try:
        # Validate required fields
        if not all([title, price, quantity, image_url, category]):
            return jsonify(response(None, "Missing required fields", 400)), 400

        conn, cursor = db_connection()
        if is_alive:
            columns = '''user_id, animal_type, category, title, description, price, quantity, is_alive, image_url, weight_per_unit, rating, discount_percentage'''
            values = [current_user, animal_type, category, title, description, price, quantity, is_alive, image_url, weight_per_unit, rating, discount_percentage]

            if animal_stage is not None:
                columns += ', animal_stage'
                values.append(animal_stage)

            cursor.execute(f'''
                INSERT INTO Products ({columns})
                VALUES ({','.join(['?'] * len(values))})
            ''', values)
        elif is_fresh:
            cursor.execute('''
                INSERT INTO Products (user_id, category, title, description, price, quantity, is_fresh, image_url, weight_per_unit, rating, discount_percentage)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (current_user, category, title, description, price, quantity, is_fresh, image_url, weight_per_unit, rating, discount_percentage))
        product_id = cursor.lastrowid  # Get ID before closing
        conn.commit()
        conn.close()
        
        if is_alive:
            data = {
            'id': product_id,
            'title': title,
            'category': category,
            'animal_type': animal_type,
            'description': description,
            'price': price,
            'quantity': quantity,
            'is_live': is_alive,
            'image_url': image_url,
            'weight_per_unit': weight_per_unit,
            'rating': rating,
            'discount_percentage': discount_percentage,
            'animal_stage': animal_stage
        }
        else:
            data = {
            'id': product_id,
            'title': title,
            'category': category,
            'description': description,
            'price': price,
            'quantity': quantity,
            'is_fresh': is_fresh,
            'image_url': image_url,
            'weight_per_unit': weight_per_unit,
            'rating': rating,
            'discount_percentage': discount_percentage
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
    category = data.get('category')
    animal_type = data.get('animal_type')
    description = request.form.get('description')
    price = data.get('price')
    quantity = data.get('quantity')
    is_alive = data.get('is_live', 'false')
    is_fresh = data.get('is_fresh', 'true')
    rating = float(data.get('rating', 4.0))
    discount_percentage = data.get('discount_percentage')
    weight_per_unit = float(data.get('weight_per_unit', 1.0))
    animal_stage = data.get('animal_stage', None)

    # Get the image file
    image_url = data.get('image_url')

    # Validate required fields
    if not all([title, category, price, quantity, image_url]):
        return jsonify(response(None, "Missing required fields", 400)), 400
    
    try:
        conn, cursor = db_connection()
        if is_alive:
            cursor.execute('''
                UPDATE Products
                SET title = ?, animal_type = ?, category = ?, description = ?, price = ?, quantity = ?, is_alive = ?, image_url = ?, rating = ?, discount_percentage = ?, weight_per_unit = ?, animal_stage = ?
                WHERE id = ? AND user_id = ?
            ''', (title, animal_type, category, description, price, quantity, is_alive, image_url, rating, discount_percentage, weight_per_unit, animal_stage, product_id, current_user))
        elif is_fresh:
            cursor.execute('''
                UPDATE Products
                SET title = ?, animal_type = ?, category, description = ?, price = ?, quantity = ?, is_fresh = ?, image_url = ?, rating = ?, discount_percentage = ?, weight_per_unit = ?
                WHERE id = ? AND user_id = ?
            ''', (title, animal_type, category, description, price, quantity, is_fresh, image_url, rating, discount_percentage, weight_per_unit, product_id, current_user))
        
        conn.commit()
        if cursor.rowcount == 0:
            conn.close()
            return jsonify(response(None, "Product not found or not authorized", 404)), 404
        
        conn.close()
        
        if is_alive:
            data = {
                'id': product_id,
                'title': title,
                'category': category,
                'animal_type': animal_type,
                'description': description,
                'price': price,
                'quantity': quantity,
                'is_live': is_alive,
                'image_url': image_url,
                'weight_per_unit': weight_per_unit,
                'rating': rating,
                'discount_percentage': discount_percentage,
                'animal_stage': animal_stage
            }
        else:
            data = {
                'id': product_id,
                'title': title,
                'category': category,
                'description': description,
                'price': price,
                'quantity': quantity,
                'is_fresh': is_fresh,
                'image_url': image_url,
                'weight_per_unit': weight_per_unit,
                'rating': rating,
                'discount_percentage': discount_percentage
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
        cursor.execute('DELETE FROM Products WHERE id = ? AND user_id = ?', (product_id, current_user))
        conn.commit()
        
        if cursor.rowcount == 0:
            conn.close()
            return jsonify(response(None, "Product not found or not authorized", 404)), 404
        
        conn.close()
        return jsonify(response(None, "Product deleted successfully", 200)), 200

    except Exception as e:
        return jsonify(response(None, f"Error: {e}", 500)), 500
    

@products.route('/all', methods=['DELETE'])
@jwt_required()
def delete_all_products():
    current_user = get_jwt_identity()
    try:
        conn, cursor = db_connection()
        cursor.execute('DELETE FROM Products WHERE user_id = ?', (current_user,))
        conn.commit()
        
        if cursor.rowcount == 0:
            conn.close()
            return jsonify(response(None, "No products found for this user", 404)), 404
        
        conn.close()
        return jsonify(response(None, "All products deleted successfully", 200)), 200

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
    
    
@products.route('/stats/overview', methods=['GET'])
@jwt_required()
def overview_stats():
    current_user = get_jwt_identity()
    try:
        conn, cursor = db_connection()

        # ==============================
        # Total products
        # ==============================
        cursor.execute("SELECT COUNT(*) as total FROM Products WHERE user_id = ?", (current_user,))
        total_products = cursor.fetchone()["total"]

        # Products added in the last 7 days
        one_week_ago = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute(
            "SELECT COUNT(*) as recent FROM Products WHERE user_id = ? AND created_at >= ?",
            (current_user, one_week_ago)
        )
        recent_products = cursor.fetchone()["recent"]

        # ==============================
        # Revenue stats
        # ==============================
        cursor.execute("""
            SELECT IFNULL(SUM(total_price), 0) as total_revenue
            FROM Orders
            WHERE user_id = ? AND status = 'completed'
        """, (current_user,))
        total_revenue = cursor.fetchone()["total_revenue"]

        first_day_of_month = datetime.now().replace(day=1).strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute("""
            SELECT IFNULL(SUM(total_price), 0) as monthly_revenue
            FROM Orders
            WHERE user_id = ? AND status = 'completed' AND created_at >= ?
        """, (current_user, first_day_of_month))
        monthly_revenue = cursor.fetchone()["monthly_revenue"]

        conn.close()

        return jsonify(response({
            "totalProducts": total_products,
            "recentProducts": recent_products,
            "totalRevenue": total_revenue,
            "monthlyRevenue": monthly_revenue
        }, "Overview stats fetched", 200)), 200

    except Exception as e:
        return jsonify(response(None, f"Error: {e}", 500)), 500

