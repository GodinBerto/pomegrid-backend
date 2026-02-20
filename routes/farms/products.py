import json
import logging
from datetime import datetime, timedelta

import cloudinary
from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity

from database import db_connection
from decorators.roles import user_required
from extensions.redis_client import get_redis_client
from routes import response

# Initialize the Flask auth
products = Blueprint('products', __name__)
logger = logging.getLogger(__name__)

PRODUCTS_LIST_CACHE_KEY = "farms:products:list"
PRODUCT_TYPES_CACHE_KEY = "farms:products:types"
PRODUCT_CACHE_KEY_PREFIX = "farms:products:item"
PRODUCT_IMAGE_CACHE_KEY_PREFIX = "farms:products:image"
PRODUCT_OVERVIEW_CACHE_KEY_PREFIX = "farms:products:overview"


def _cache_get(key):
    try:
        redis_client = get_redis_client()
        payload = redis_client.get(key)
        return json.loads(payload) if payload else None
    except Exception as e:
        logger.warning("Redis unavailable, skipping products cache read: %s", e)
        return None


def _cache_set(key, value, ttl=60):
    try:
        redis_client = get_redis_client()
        redis_client.setex(key, ttl, json.dumps(value))
    except Exception as e:
        logger.warning("Redis unavailable, skipping products cache write: %s", e)


def _cache_delete(*keys):
    if not keys:
        return
    try:
        redis_client = get_redis_client()
        redis_client.delete(*keys)
    except Exception as e:
        logger.warning("Redis unavailable, skipping products cache delete: %s", e)


def _cache_delete_patterns(*patterns):
    try:
        redis_client = get_redis_client()
        keys = []
        for pattern in patterns:
            keys.extend(redis_client.keys(pattern))
        if keys:
            redis_client.delete(*keys)
    except Exception as e:
        logger.warning("Redis unavailable, skipping products cache pattern delete: %s", e)


def _product_cache_key(product_id):
    return f"{PRODUCT_CACHE_KEY_PREFIX}:{product_id}"


def _product_image_cache_key(product_id):
    return f"{PRODUCT_IMAGE_CACHE_KEY_PREFIX}:{product_id}"


def _product_overview_cache_key(user_id):
    return f"{PRODUCT_OVERVIEW_CACHE_KEY_PREFIX}:{user_id}"


def _invalidate_product_cache(product_id=None, user_id=None):
    keys = [PRODUCTS_LIST_CACHE_KEY, PRODUCT_TYPES_CACHE_KEY]
    if product_id is not None:
        keys.append(_product_cache_key(product_id))
        keys.append(_product_image_cache_key(product_id))
    if user_id is not None:
        keys.append(_product_overview_cache_key(user_id))
    _cache_delete(*keys)
    _cache_delete_patterns(f"{PRODUCT_OVERVIEW_CACHE_KEY_PREFIX}:*")

@products.route('/', methods=['GET'])
def get_products():
    cached = _cache_get(PRODUCTS_LIST_CACHE_KEY)
    if cached is not None:
        logger.info("Products list served from cache")
        return jsonify(response(cached, "Successfully retrieved products.", 200)), 200

    try:
        conn, cursor = db_connection()
        cursor.execute('SELECT * FROM Products')
        rows = cursor.fetchall()
        products = [dict(row) for row in rows]
        conn.close()

        _cache_set(PRODUCTS_LIST_CACHE_KEY, products)
        logger.info("Products list loaded from DB")
        return jsonify(response(products, "Successfully retrieved products.", 200)), 200

    except Exception as e:
        logger.exception("Failed to fetch products list")
        return jsonify(response( [],f"Error: {e}", 500)), 500
    

@products.route('/<int:product_id>', methods=['GET'])
@user_required
def get_product(product_id):
    cache_key = _product_cache_key(product_id)
    cached = _cache_get(cache_key)
    if cached is not None:
        logger.info("Product %s served from cache", product_id)
        return jsonify(response(cached, "Successfully retrieved product.", 200)), 200

    try:
        conn, cursor = db_connection()
        cursor.execute('SELECT * FROM Products WHERE id = ?', (product_id,))
        row = cursor.fetchone()
        if row:
            product = dict(row)
            conn.close()
            _cache_set(cache_key, product)
            logger.info("Product %s loaded from DB", product_id)
            return jsonify(response(product, "Successfully retrieved product.", 200)), 200
        else:
            conn.close()
            return jsonify(response(None, "Product not found", 404)), 404

    except Exception as e:
        logger.exception("Failed to fetch product %s", product_id)
        return jsonify(response(None, f"Error: {e}", 500)), 500
    

# Product types GET endpoint
@products.route('/types', methods=['GET'])
@user_required
def get_product_types():
    cached = _cache_get(PRODUCT_TYPES_CACHE_KEY)
    if cached is not None:
        logger.info("Product types served from cache")
        return jsonify(response(cached, "Successfully retrieved product types.", 200)), 200

    try:
        conn, cursor = db_connection()
        cursor.execute('SELECT * FROM ProductTypes')
        rows = cursor.fetchall()
        product_types = [dict(row) for row in rows]
        conn.close()
        _cache_set(PRODUCT_TYPES_CACHE_KEY, product_types)
        logger.info("Product types loaded from DB")
        return jsonify(response(product_types, "Successfully retrieved product types.", 200)), 200

    except Exception as e:
        logger.exception("Failed to fetch product types")
        return jsonify(response([], f"Error: {e}", 500)), 500


@products.route('/', methods=['POST'])
@user_required
def add_product():
    data = request.get_json() or {}
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

        _invalidate_product_cache(product_id=product_id, user_id=current_user)
        logger.info("Product %s created by user %s", product_id, current_user)
        return jsonify(response(data, "Product added successfully", 201)), 201

    except Exception as e:
        logger.exception("Failed to create product for user %s", current_user)
        return jsonify(response(None, f"Error: {e}", 500)), 500
    

@products.route('/<int:product_id>', methods=['PUT'])
@user_required
def update_product(product_id):
    data = request.get_json() or {}
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
        
        _invalidate_product_cache(product_id=product_id, user_id=current_user)
        logger.info("Product %s updated by user %s", product_id, current_user)
        return jsonify(response(data, "Product updated successfully", 200)), 200
    except Exception as e:
        logger.exception("Failed to update product %s", product_id)
        return jsonify(response(None, f"Error: {e}", 500)), 500
    

@products.route('/<int:product_id>', methods=['DELETE'])
@user_required
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
        _invalidate_product_cache(product_id=product_id, user_id=current_user)
        logger.info("Product %s deleted by user %s", product_id, current_user)
        return jsonify(response(None, "Product deleted successfully", 200)), 200

    except Exception as e:
        logger.exception("Failed to delete product %s", product_id)
        return jsonify(response(None, f"Error: {e}", 500)), 500
    

@products.route('/all', methods=['DELETE'])
@user_required
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
        _invalidate_product_cache(user_id=current_user)
        _cache_delete_patterns(f"{PRODUCT_CACHE_KEY_PREFIX}:*", f"{PRODUCT_IMAGE_CACHE_KEY_PREFIX}:*")
        logger.info("All products deleted by user %s", current_user)
        return jsonify(response(None, "All products deleted successfully", 200)), 200

    except Exception as e:
        logger.exception("Failed to delete all products for user %s", current_user)
        return jsonify(response(None, f"Error: {e}", 500)), 500
    
    
@products.route('/<int:product_id>/image', methods=['POST'])
@user_required
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
        _invalidate_product_cache(product_id=product_id, user_id=current_user)
        _cache_set(_product_image_cache_key(product_id), {"image_url": image_url})
        logger.info("Image uploaded for product %s by user %s", product_id, current_user)
        return jsonify(response({'image_url': image_url}, "Image uploaded successfully", 200)), 200

    except Exception as e:
        logger.exception("Failed to upload image for product %s", product_id)
        return jsonify(response(None, f"Error: {e}", 500)), 500
    

@products.route('/<int:product_id>/image', methods=['GET'])
@user_required
def get_product_image(product_id):
    cache_key = _product_image_cache_key(product_id)
    cached = _cache_get(cache_key)
    if cached is not None:
        logger.info("Product image served from cache for product %s", product_id)
        return jsonify(response(cached, "Image retrieved successfully", 200)), 200

    try:
        conn, cursor = db_connection()
        cursor.execute('SELECT image_url FROM Products WHERE id = ?', (product_id,))
        row = cursor.fetchone()
        if row and row['image_url']:
            image_url = row['image_url']
            conn.close()
            payload = {'image_url': image_url}
            _cache_set(cache_key, payload)
            logger.info("Product image loaded from DB for product %s", product_id)
            return jsonify(response(payload, "Image retrieved successfully", 200)), 200
        else:
            conn.close()
            return jsonify(response(None, "Image not found", 404)), 404

    except Exception as e:
        logger.exception("Failed to fetch image for product %s", product_id)
        return jsonify(response(None, f"Error: {e}", 500)), 500
    

@products.route('/<int:product_id>/image', methods=['DELETE'])
@user_required
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
        _invalidate_product_cache(product_id=product_id, user_id=current_user)
        logger.info("Image deleted for product %s by user %s", product_id, current_user)
        return jsonify(response(None, "Image deleted successfully", 200)), 200

    except Exception as e:
        logger.exception("Failed to delete image for product %s", product_id)
        return jsonify(response(None, f"Error: {e}", 500)), 500
    
    
@products.route('/stats/overview', methods=['GET'])
@user_required
def overview_stats():
    current_user = get_jwt_identity()
    cache_key = _product_overview_cache_key(current_user)
    cached = _cache_get(cache_key)
    if cached is not None:
        logger.info("Product overview served from cache for user %s", current_user)
        return jsonify(response(cached, "Overview stats fetched", 200)), 200

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

        payload = {
            "totalProducts": total_products,
            "recentProducts": recent_products,
            "totalRevenue": total_revenue,
            "monthlyRevenue": monthly_revenue
        }
        _cache_set(cache_key, payload)
        logger.info("Product overview loaded from DB for user %s", current_user)

        return jsonify(response(payload, "Overview stats fetched", 200)), 200

    except Exception as e:
        logger.exception("Failed to fetch product overview for user %s", current_user)
        return jsonify(response(None, f"Error: {e}", 500)), 500

