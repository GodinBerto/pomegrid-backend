from flask import request, jsonify
from decorators.rate_limit import rate_limit
from database import db_connection
from services.passwords import hash_password
from routes.api_envelope import envelope
from . import food_trade_api

@food_trade_api.route("/auth/register", methods=["POST"])
@rate_limit("food-trade-auth-register", limit=20, window_seconds=60)
def register():
    data = request.get_json() or {}
    full_name = str(data.get("full_name") or "").strip()
    email = str(data.get("email") or "").strip().lower()
    password = data.get("password")
    phone = str(data.get("phone") or "").strip()
    region = str(data.get("region") or "").strip()
    address = str(data.get("address") or "").strip()
    
    if not all([full_name, email, password, phone, region, address]):
        return jsonify(envelope(None, "All required fields must be provided", 400, False)), 400

    conn, cursor = db_connection()
    try:
        # Check if email exists
        cursor.execute("SELECT id FROM Users WHERE LOWER(email) = ? LIMIT 1", (email,))
        if cursor.fetchone():
            return jsonify(envelope(None, "Email already exists", 409, False)), 409

        hashed_password = hash_password(password)
        username = email.split('@')[0] # Simple username derivation

        cursor.execute(
            """
            INSERT INTO Users (
                username, email, password_hash, full_name, phone,
                user_type, role, address, is_verified, accepted_policy, policy_accepted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
            """,
            (username, email, hashed_password, full_name, phone, "user", "user", address, 0)
        )
        user_id = cursor.lastrowid
        
        cursor.execute(
            """
            INSERT INTO food_trade_extended_user (
                user_id, address, region
            ) VALUES (?, ?, ?)
            """,
            (user_id, address, region)
        )
        
        conn.commit()
        return jsonify(envelope({"user_id": user_id}, "User registered successfully.", 201)), 201
    except Exception as exc:
        conn.rollback()
        return jsonify(envelope(None, f"Internal server error: {str(exc)}", 500, False)), 500
    finally:
        conn.close()
