
from flask import Blueprint, g, jsonify, request
from flask_jwt_extended import jwt_required

from database.connection import db_connection
from middleware.authMiddleware import get_authenticated_user_id
from routes.api_envelope import envelope
from routes.authentication.authentication import _build_auth_user_payload

intro_users = Blueprint("intro_users", __name__)

def getIntroUser(user_id):
    """
    Checks if the user has an account for the intro app.
    Returns the database row if they do, or a Flask error response if they don't.
    """
    if user_id is None:
        return jsonify(envelope(None, "No user found", 404, False)), 404
    
    conn, cursor = db_connection()
    cursor.execute(
        """
        SELECT id, role 
        FROM IntroUsers 
        WHERE user_id = ?
        """,
        (user_id,)
    )
    row = cursor.fetchone()
    conn.close()

    # Prevent user from accessing the app if they aren't invited/don't have a record
    if not row:
        return jsonify(envelope(None, "Access denied: You are not invited to the intro app.", 403, False)), 403
        
    return row


@intro_users.route("/me", methods=["GET"])
@jwt_required()
def auth_me():
    user_id = get_authenticated_user_id()
    if user_id is None:
        return jsonify(envelope(None, "Invalid token identity", 401, False)), 401

    # 1. Use the helper function to check access and fetch the intro user
    result = getIntroUser(user_id)
    
    # If the helper returned a tuple, it's an error response (e.g. 403 Forbidden)
    if isinstance(result, tuple):
        return result
    
    # Otherwise, it returned the database row
    row = result

    # 2. Build the payload dictionary correctly
    # If you're using sqlite3.Row, you can access by key (row["role"]), 
    # otherwise access by index (row[1]) depending on your db_connection setup
    try:
        payload = {
            "intro_user_id": row["id"],
            "role": row["role"]
        }
    except TypeError:
        # Fallback if cursor.fetchone() returns a standard tuple instead of a dict
        payload = {
            "intro_user_id": row[0],
            "role": row[1]
        }

    return jsonify(envelope(payload, "Success", 200, True)), 200
