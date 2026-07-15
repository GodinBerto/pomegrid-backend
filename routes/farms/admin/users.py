import logging

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity

from database import db_connection
from decorators.roles import admin_required
from routes import response
from middleware.authMiddleware import normalize_role, ROLE_ADMIN, ROLE_USER, ROLE_WORKER


users_admin = Blueprint("users_admin", __name__)
logger = logging.getLogger(__name__)

VALID_ROLES = [ROLE_ADMIN, ROLE_USER, ROLE_WORKER]


@users_admin.route("/<int:user_id>/role", methods=["PUT"])
@users_admin.route("/<int:user_id>/role", methods=["PATCH"])
@admin_required
def update_user_role(user_id):
    """
    Update a user's role. Admin-only endpoint.
    
    Request body:
    {
        "role": "user" | "worker" | "admin"
    }
    
    Returns: Updated user object with new role
    """
    data = request.get_json() or {}
    
    # Validate that a role was provided
    if "role" not in data or not data.get("role"):
        return jsonify(response(None, "Role is required", 400)), 400
    
    new_role = str(data.get("role") or "").strip().lower()
    
    # Validate the role is one of the allowed values
    if new_role not in VALID_ROLES:
        return jsonify(
            response(
                None, 
                f"Invalid role. Must be one of: {', '.join(VALID_ROLES)}", 
                400
            )
        ), 400
    
    # Prevent updating own role
    admin_id = int(get_jwt_identity())
    if user_id == admin_id:
        return jsonify(
            response(None, "Cannot update your own role", 400)
        ), 400
    
    try:
        conn, cursor = db_connection()
        
        # Check if user exists
        cursor.execute(
            """
            SELECT id, full_name, email, role, user_type, is_admin
            FROM Users
            WHERE id = ?
            """,
            (user_id,)
        )
        user = cursor.fetchone()
        
        if not user:
            conn.close()
            return jsonify(response(None, "User not found", 404)), 404
        
        # Determine is_admin flag based on new role
        is_admin = 1 if new_role == ROLE_ADMIN else 0
        
        # Update user role
        cursor.execute(
            """
            UPDATE Users
            SET
                role = ?,
                user_type = ?,
                is_admin = ?
            WHERE id = ?
            """,
            (new_role, new_role, is_admin, user_id)
        )
        
        conn.commit()
        
        # Fetch updated user
        cursor.execute(
            """
            SELECT id, full_name, email, role, user_type, is_admin
            FROM Users
            WHERE id = ?
            """,
            (user_id,)
        )
        updated_user = cursor.fetchone()
        conn.close()
        
        # Format response
        user_data = {
            "id": updated_user["id"],
            "full_name": updated_user["full_name"],
            "email": updated_user["email"],
            "role": updated_user["role"],
            "user_type": updated_user["user_type"],
            "is_admin": bool(updated_user["is_admin"])
        }
        
        logger.info(f"Admin {admin_id} updated user {user_id} role to {new_role}")
        return jsonify(response(user_data, "User role updated successfully", 200)), 200
        
    except Exception as e:
        logger.exception(f"Failed to update user {user_id} role")
        return jsonify(response(None, f"Error: {e}", 500)), 500
