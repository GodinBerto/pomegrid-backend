from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from database import db_connection
from routes import response


users = Blueprint('users', __name__)


@users.route("/me", methods=["GET"])
@jwt_required()
def get_current_user():
    user_id = get_jwt_identity()  # 🔐 from access token

    try:
        conn, cursor = db_connection()
        cursor.execute(
            "SELECT id, email, full_name FROM Users WHERE id = ?",
            (user_id,)
        )
        row = cursor.fetchone()
        conn.close()

        if not row:
            return jsonify(response(None, "User not found", 404)), 404

        return jsonify(response(dict(row), "User retrieved", 200)), 200

    except Exception as e:
        return jsonify(response(None, f"Error: {e}", 500)), 500
