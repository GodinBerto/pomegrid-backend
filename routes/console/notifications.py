from flask import jsonify, request
from flask_jwt_extended import jwt_required

from database import db_connection
from decorators.roles import get_authenticated_user_id
from routes.api_envelope import envelope
from . import console_bp

@console_bp.route("/notifications", methods=["GET"])
@jwt_required()
def get_notifications():
    user_id = get_authenticated_user_id()
    app_name = request.args.get("app")
    
    try:
        conn, cursor = db_connection()
        query = "SELECT * FROM notifications WHERE user_id = ?"
        params = [user_id]
        
        if app_name:
            query += " AND app = ?"
            params.append(app_name)
            
        query += " ORDER BY created_at DESC"
        
        cursor.execute(query, params)
        items = [dict(row) for row in cursor.fetchall()]
        return jsonify(envelope(items, "Notifications fetched successfully")), 200
    except Exception as e:
        return jsonify(envelope(None, str(e), 500, False)), 500
