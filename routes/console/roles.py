import uuid
from flask import request, jsonify
from flask_jwt_extended import jwt_required

from database import db_connection
from decorators.roles import get_authenticated_user_id
from routes.api_envelope import envelope
from . import console_bp


@console_bp.route("/roles", methods=["POST"])
@console_bp.route("/", methods=["POST"])
@jwt_required()
def create_user_role():
    data = request.get_json() or {}
    user_id = data.get("user_id")
    role = data.get("role", "worker")
    
    if not user_id:
        return jsonify(envelope(None, "user_id is required", 400, False)), 400
        
    role_id = str(uuid.uuid4())
    try:
        conn, cursor = db_connection()
        cursor.execute(
            """
            INSERT INTO Console_User_Roles (id, user_id, role)
            VALUES (?, ?, ?)
            """,
            (role_id, user_id, role)
        )
        conn.commit()
        return jsonify(envelope({"id": role_id}, "Role created successfully", 201)), 201
    except Exception as e:
        return jsonify(envelope(None, str(e), 500, False)), 500


@console_bp.route("/roles/user", methods=["GET"])
@jwt_required()
def get_user_roles_by_token():
    user_id = get_authenticated_user_id()
    if not user_id:
        return jsonify(envelope(None, "Invalid token identity", 401, False)), 401
        
    try:
        conn, cursor = db_connection()
        cursor.execute("SELECT * FROM Console_User_Roles WHERE user_id = ?", (user_id,))
        roles = [dict(row) for row in cursor.fetchall()]
        return jsonify(envelope(roles, "User roles fetched successfully")), 200
    except Exception as e:
        return jsonify(envelope(None, str(e), 500, False)), 500


@console_bp.route("/roles", methods=["GET"])
@jwt_required()
def get_all_user_roles():
    try:
        conn, cursor = db_connection()
        cursor.execute("SELECT * FROM Console_User_Roles")
        roles = [dict(row) for row in cursor.fetchall()]
        return jsonify(envelope(roles, "User roles fetched successfully")), 200
    except Exception as e:
        return jsonify(envelope(None, str(e), 500, False)), 500


@console_bp.route("/roles/<role_id>", methods=["GET"])
@jwt_required()
def get_user_role_by_id(role_id):
    try:
        conn, cursor = db_connection()
        cursor.execute("SELECT * FROM Console_User_Roles WHERE id = ?", (role_id,))
        row = cursor.fetchone()
        if not row:
            return jsonify(envelope(None, "Role not found", 404, False)), 404
        return jsonify(envelope(dict(row), "User role fetched successfully")), 200
    except Exception as e:
        return jsonify(envelope(None, str(e), 500, False)), 500


@console_bp.route("/roles/<role_id>", methods=["PUT"])
@jwt_required()
def update_user_role(role_id):
    data = request.get_json() or {}
    role = data.get("role")
    
    if not role:
        return jsonify(envelope(None, "role is required", 400, False)), 400

    try:
        conn, cursor = db_connection()
        cursor.execute("UPDATE Console_User_Roles SET role = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (role, role_id))
        if cursor.rowcount == 0:
            return jsonify(envelope(None, "Role not found", 404, False)), 404
        conn.commit()
        return jsonify(envelope({"id": role_id}, "Role updated successfully")), 200
    except Exception as e:
        return jsonify(envelope(None, str(e), 500, False)), 500


@console_bp.route("/roles/<role_id>", methods=["DELETE"])
@jwt_required()
def delete_user_role(role_id):
    try:
        conn, cursor = db_connection()
        cursor.execute("DELETE FROM Console_User_Roles WHERE id = ?", (role_id,))
        if cursor.rowcount == 0:
            return jsonify(envelope(None, "Role not found", 404, False)), 404
        conn.commit()
        return jsonify(envelope(None, "Role deleted successfully")), 200
    except Exception as e:
        return jsonify(envelope(None, str(e), 500, False)), 500
