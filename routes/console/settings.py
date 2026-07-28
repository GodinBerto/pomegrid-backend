from flask import jsonify, request
from flask_jwt_extended import jwt_required

from database import db_connection
from decorators.roles import get_authenticated_user_id
from routes.api_envelope import envelope
from services.passwords import hash_password, verify_password
from . import console_bp

@console_bp.route("/settings/personal", methods=["GET"])
@jwt_required()
def get_personal_settings():
    user_id = get_authenticated_user_id()
    try:
        conn, cursor = db_connection()
        cursor.execute("SELECT full_name, phone, email FROM Users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        if not row:
            return jsonify(envelope(None, "User not found", 404, False)), 404
            
        return jsonify(envelope(dict(row), "Personal settings fetched")), 200
    except Exception as e:
        return jsonify(envelope(None, str(e), 500, False)), 500

@console_bp.route("/settings/personal", methods=["PUT"])
@jwt_required()
def update_personal_settings():
    user_id = get_authenticated_user_id()
    data = request.get_json() or {}
    
    full_name = data.get("full_name")
    phone = data.get("phone")
    email = data.get("email")
    
    if not full_name or not email:
        return jsonify(envelope(None, "Full name and email are required", 400, False)), 400
        
    try:
        conn, cursor = db_connection()
        cursor.execute(
            "UPDATE Users SET full_name = ?, phone = ?, email = ? WHERE id = ?",
            (full_name, phone, email, user_id)
        )
        conn.commit()
        return jsonify(envelope(None, "Personal information updated successfully")), 200
    except Exception as e:
        if "UNIQUE constraint failed" in str(e):
            return jsonify(envelope(None, "Email already in use", 409, False)), 409
        return jsonify(envelope(None, str(e), 500, False)), 500

@console_bp.route("/settings/security", methods=["PUT"])
@jwt_required()
def update_security_settings():
    user_id = get_authenticated_user_id()
    data = request.get_json() or {}
    
    current_password = data.get("current_password")
    new_password = data.get("new_password")
    
    if not current_password or not new_password:
        return jsonify(envelope(None, "Both current and new passwords are required", 400, False)), 400
        
    try:
        conn, cursor = db_connection()
        cursor.execute("SELECT password_hash FROM Users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        if not row:
            return jsonify(envelope(None, "User not found", 404, False)), 404
            
        if not verify_password(row["password_hash"], current_password):
            return jsonify(envelope(None, "Invalid current password", 400, False)), 400
            
        new_hashed = hash_password(new_password)
        cursor.execute("UPDATE Users SET password_hash = ? WHERE id = ?", (new_hashed, user_id))
        conn.commit()
        
        return jsonify(envelope(None, "Password updated successfully")), 200
    except Exception as e:
        return jsonify(envelope(None, str(e), 500, False)), 500

@console_bp.route("/settings/notifications", methods=["GET"])
@jwt_required()
def get_notification_settings():
    user_id = get_authenticated_user_id()
    try:
        conn, cursor = db_connection()
        cursor.execute("SELECT setting_id, enabled FROM user_notification_preferences WHERE user_id = ?", (user_id,))
        rows = cursor.fetchall()
        
        # Default settings if none exist
        prefs = {
            "budget": True,
            "payroll": True,
            "weekly": False
        }
        for row in rows:
            if row["setting_id"] in prefs:
                prefs[row["setting_id"]] = bool(row["enabled"])
                
        return jsonify(envelope(prefs, "Notification preferences fetched")), 200
    except Exception as e:
        return jsonify(envelope(None, str(e), 500, False)), 500

@console_bp.route("/settings/notifications", methods=["PUT"])
@jwt_required()
def update_notification_settings():
    user_id = get_authenticated_user_id()
    data = request.get_json() or {}
    
    # We expect keys like 'budget', 'payroll', 'weekly' with boolean values
    try:
        conn, cursor = db_connection()
        for key in ["budget", "payroll", "weekly"]:
            if key in data:
                val = 1 if data[key] else 0
                # Upsert preference
                cursor.execute(
                    """
                    INSERT INTO user_notification_preferences (user_id, setting_id, enabled, updated_at)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(user_id, setting_id) DO UPDATE SET
                    enabled = excluded.enabled,
                    updated_at = excluded.updated_at
                    """,
                    (user_id, key, val)
                )
        conn.commit()
        return jsonify(envelope(None, "Notification preferences updated")), 200
    except Exception as e:
        return jsonify(envelope(None, str(e), 500, False)), 500
