from flask import Blueprint, jsonify
from flask_jwt_extended import get_jwt_identity, jwt_required
from database import db_connection
from routes import response

users = Blueprint('users', __name__)

@users.route('/<int:user_id>', methods=['GET'])
@jwt_required()
def get_user(user_id):
    identity = get_jwt_identity()

    # Optional: Check if the user is accessing their own data
    if str(identity) != str(user_id):
        return jsonify(response(None, "Unauthorized access", 403)), 403

    try:
        conn, cursor = db_connection()
        cursor.execute('SELECT email, full_name FROM Users WHERE id = ?', (user_id,))
        row = cursor.fetchone()
        if row:
            user = dict(row)
            conn.close()
            return jsonify(response(user, "Successfully retrieved user.", 200)), 200
        else:
            conn.close()
            return jsonify(response(None, "User not found", 404)), 404
    except Exception as e:
        return jsonify(response(None, f"Error: {e}", 500)), 500