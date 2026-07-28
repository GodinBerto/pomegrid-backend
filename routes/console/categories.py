import uuid
from flask import request, jsonify
from flask_jwt_extended import jwt_required

from database import db_connection
from decorators.roles import get_authenticated_user_id
from routes.api_envelope import envelope
from . import console_bp


@console_bp.route("/categories", methods=["POST"])
@jwt_required()
def create_category():
    user_id = get_authenticated_user_id()
    data = request.get_json() or {}
    name = data.get("name")
    description = data.get("description", "")
    
    if not name:
        return jsonify(envelope(None, "name is required", 400, False)), 400
        
    cat_id = str(uuid.uuid4())
    try:
        conn, cursor = db_connection()
        cursor.execute(
            """
            INSERT INTO Console_Categories (id, name, description, created_by)
            VALUES (?, ?, ?, ?)
            """,
            (cat_id, name, description, user_id)
        )
        conn.commit()
        return jsonify(envelope({"id": cat_id}, "Category created successfully", 201)), 201
    except Exception as e:
        return jsonify(envelope(None, str(e), 500, False)), 500


@console_bp.route("/categories", methods=["GET"])
@jwt_required()
def get_categories():
    try:
        conn, cursor = db_connection()
        cursor.execute("SELECT * FROM Console_Categories")
        items = [dict(row) for row in cursor.fetchall()]
        return jsonify(envelope(items, "Categories fetched successfully")), 200
    except Exception as e:
        return jsonify(envelope(None, str(e), 500, False)), 500


@console_bp.route("/categories/<cat_id>", methods=["GET"])
@jwt_required()
def get_category_by_id(cat_id):
    try:
        conn, cursor = db_connection()
        cursor.execute("SELECT * FROM Console_Categories WHERE id = ?", (cat_id,))
        row = cursor.fetchone()
        if not row:
            return jsonify(envelope(None, "Category not found", 404, False)), 404
        return jsonify(envelope(dict(row), "Category fetched successfully")), 200
    except Exception as e:
        return jsonify(envelope(None, str(e), 500, False)), 500


@console_bp.route("/categories/<cat_id>", methods=["PUT"])
@jwt_required()
def update_category(cat_id):
    data = request.get_json() or {}
    name = data.get("name")
    description = data.get("description")
    
    if not name:
        return jsonify(envelope(None, "name is required", 400, False)), 400

    try:
        conn, cursor = db_connection()
        cursor.execute(
            "UPDATE Console_Categories SET name = ?, description = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", 
            (name, description, cat_id)
        )
        if cursor.rowcount == 0:
            return jsonify(envelope(None, "Category not found", 404, False)), 404
        conn.commit()
        return jsonify(envelope({"id": cat_id}, "Category updated successfully")), 200
    except Exception as e:
        return jsonify(envelope(None, str(e), 500, False)), 500


@console_bp.route("/categories/<cat_id>", methods=["DELETE"])
@jwt_required()
def delete_category(cat_id):
    try:
        conn, cursor = db_connection()
        cursor.execute("DELETE FROM Console_Categories WHERE id = ?", (cat_id,))
        if cursor.rowcount == 0:
            return jsonify(envelope(None, "Category not found", 404, False)), 404
        conn.commit()
        return jsonify(envelope(None, "Category deleted successfully")), 200
    except Exception as e:
        return jsonify(envelope(None, str(e), 500, False)), 500
