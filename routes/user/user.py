import logging
from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from database import db_connection
from routes import response


users = Blueprint('users', __name__)
logger = logging.getLogger(__name__)


def _serialize_user_row(row):
    user = dict(row)
    user["is_admin"] = bool(user.get("is_admin"))
    user["is_active"] = bool(user.get("is_active"))
    user["is_verified"] = bool(user.get("is_verified"))
    return user


@users.route("/me", methods=["GET"])
@jwt_required()
def get_current_user():
    user_id = get_jwt_identity()

    try:
        conn, cursor = db_connection()
        cursor.execute(
            """
            SELECT
                id,
                username,
                email,
                full_name,
                phone,
                user_type,
                is_admin,
                is_active,
                is_verified,
                address,
                profile_image_url,
                date_of_birth,
                created_at,
                updated_at
            FROM Users
            WHERE id = ?
            """,
            (user_id,),
        )
        row = cursor.fetchone()
        conn.close()

        if not row:
            return jsonify(response(None, "User not found", 404)), 404

        return jsonify(response(_serialize_user_row(row), "User retrieved", 200)), 200

    except Exception as e:
        logger.exception("Failed to fetch current user")
        return jsonify(response(None, f"Error: {e}", 500)), 500


@users.route("/me", methods=["PUT"])
@jwt_required()
def update_current_user():
    user_id = get_jwt_identity()
    data = request.get_json() or {}
    allowed_fields = ["full_name", "phone", "address", "profile_image_url", "date_of_birth"]
    updates = {k: data[k] for k in allowed_fields if k in data}
    if not updates:
        return jsonify(response(None, "No profile fields provided", 400)), 400

    set_clause = ", ".join([f"{k} = ?" for k in updates.keys()])
    values = list(updates.values())
    values.append(user_id)

    try:
        conn, cursor = db_connection()
        cursor.execute(
            f"UPDATE Users SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            values,
        )
        conn.commit()
        cursor.execute(
            """
            SELECT
                id,
                username,
                email,
                full_name,
                phone,
                user_type,
                is_admin,
                is_active,
                is_verified,
                address,
                profile_image_url,
                date_of_birth,
                created_at,
                updated_at
            FROM Users
            WHERE id = ?
            """,
            (user_id,),
        )
        row = cursor.fetchone()
        conn.close()
        if not row:
            return jsonify(response(None, "User not found", 404)), 404
        return jsonify(response(_serialize_user_row(row), "User profile updated", 200)), 200
    except Exception as e:
        logger.exception("Failed to update current user")
        return jsonify(response(None, f"Error: {e}", 500)), 500
