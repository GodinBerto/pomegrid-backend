from flask import Blueprint, request, jsonify
from flask_cors import CORS
from flask_jwt_extended import get_jwt_identity, jwt_required
from database import db_connection
from routes import response

categories = Blueprint('categories', __name__)

@categories.route('/', methods=['GET'])
def get_categories():
    try:
        conn, cursor = db_connection()
        cursor.execute('SELECT * FROM Categories')
        rows = cursor.fetchall()
        categories = [dict(row) for row in rows]
        conn.close()
        return jsonify(response(categories, "Successfully retrieved categories.", 200)), 200

    except Exception as e:
        return jsonify(response([], f"Error: {e}", 500)), 500
    

@categories.route('/<int:category_id>', methods=['GET'])
@jwt_required()
def get_category(category_id):
    try:
        conn, cursor = db_connection()
        cursor.execute('SELECT * FROM Categories WHERE id = ?', (category_id,))
        row = cursor.fetchone()
        if row:
            category = dict(row)
            conn.close()
            return jsonify(response(category, "Successfully retrieved category.", 200)), 200
        else:
            conn.close()
            return jsonify(response(None, "Category not found", 404)), 404

    except Exception as e:
        return jsonify(response(None, f"Error: {e}", 500)), 500
    

@categories.route('/', methods=['POST'])
@jwt_required()
def create_category():
    try:
        data = request.get_json()
        name = data.get('name')
        description = data.get('description', '')

        if not name:
            return jsonify(response(None, "Category name is required", 400)), 400

        conn, cursor = db_connection()
        cursor.execute('INSERT INTO Categories (name, description) VALUES (?, ?)', (name, description))
        conn.commit()
        new_category_id = cursor.lastrowid
        conn.close()

        return jsonify(response({'id': new_category_id, 'name': name, 'description': description}, "Category created successfully.", 201)), 201

    except Exception as e:
        return jsonify(response(None, f"Error: {e}", 500)), 500
    

@categories.route('/<int:category_id>', methods=['PUT'])
@jwt_required()
def update_category(category_id):
    try:
        data = request.get_json()
        name = data.get('name')
        description = data.get('description', '')

        if not name:
            return jsonify(response(None, "Category name is required", 400)), 400

        conn, cursor = db_connection()
        cursor.execute('UPDATE Categories SET name = ?, description = ? WHERE id = ?', (name, description, category_id))
        conn.commit()

        if cursor.rowcount == 0:
            conn.close()
            return jsonify(response(None, "Category not found", 404)), 404

        conn.close()
        return jsonify(response({'id': category_id, 'name': name, 'description': description}, "Category updated successfully.", 200)), 200

    except Exception as e:
        return jsonify(response(None, f"Error: {e}", 500)), 500
    

@categories.route('/<int:category_id>', methods=['DELETE'])
@jwt_required()
def delete_category(category_id):
    try:
        conn, cursor = db_connection()
        cursor.execute('DELETE FROM Categories WHERE id = ?', (category_id,))
        conn.commit()

        if cursor.rowcount == 0:
            conn.close()
            return jsonify(response(None, "Category not found", 404)), 404

        conn.close()
        return jsonify(response(category_id, "Category deleted successfully.", 200)), 200

    except Exception as e:
        return jsonify(response(None, f"Error: {e}", 500)), 500