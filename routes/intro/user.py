
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

    # If there is no intro record, create one for any authenticated user so
    # all roles get access. Use the user's existing `role` from `Users` when
    # it matches an allowed intro role; otherwise fall back to `feed_seller`.
    if not row:
        try:
            conn2, cursor2 = db_connection()
            cursor2.execute("SELECT role FROM Users WHERE id = ?", (user_id,))
            user_row = cursor2.fetchone()
            user_role = None 
            if user_row:
                try:
                    user_role = (user_row["role"] or "").strip()
                except Exception:
                    # tuple-like fallback
                    user_role = (user_row[7] if len(user_row) > 7 else None) or ""

            allowed_intro_roles = {"fingerlings_seller", "catfish_seller", "tilapia_seller", "feed_seller"}
            intro_role = user_role if user_role in allowed_intro_roles else "feed_seller"

            cursor2.execute(
                "INSERT INTO IntroUsers (user_id, role, created_at, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                (user_id, intro_role),
            )
            conn2.commit()
            cursor2.execute("SELECT id, role FROM IntroUsers WHERE user_id = ?", (user_id,))
            row = cursor2.fetchone()
            return row
        finally:
            try:
                conn2.close()
            except Exception:
                pass

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
