from flask import jsonify, request
from flask_jwt_extended import jwt_required

from database.connection import db_connection
from middleware.authMiddleware import get_authenticated_user_id
from routes.api_envelope import envelope
from . import food_trade_api
from .utils import check_admin


@food_trade_api.route("/whatsapp_groups", methods=["GET"])
def list_whatsapp_groups():
    conn, cursor = db_connection()
    cursor.execute("SELECT id, region, invite_url, description, sort_order FROM food_trade_whatsapp_groups WHERE is_active = 1 ORDER BY sort_order ASC")
    rows = cursor.fetchall()
    conn.close()
    
    groups = [dict(row) for row in rows]
    return jsonify(envelope(groups, "Whatsapp groups retrieved successfully", 200, True)), 200


@food_trade_api.route("/admin/whatsapp", methods=["GET"])
@jwt_required()
def admin_list_whatsapp():
    user_id = get_authenticated_user_id()
    if not check_admin(user_id):
        return jsonify(envelope(None, "Forbidden: admin only", 403, False)), 403
        
    conn, cursor = db_connection()
    cursor.execute("SELECT id, region, invite_url, description, is_active, sort_order FROM food_trade_whatsapp_groups ORDER BY sort_order ASC")
    rows = cursor.fetchall()
    conn.close()
    return jsonify(envelope([dict(r) for r in rows], "Admin whatsapp groups", 200, True)), 200


@food_trade_api.route("/admin/whatsapp", methods=["POST"])
@jwt_required()
def admin_update_whatsapp():
    user_id = get_authenticated_user_id()
    if not check_admin(user_id):
        return jsonify(envelope(None, "Forbidden: admin only", 403, False)), 403
        
    data = request.json
    wid = data.get("id")
    invite_url = data.get("invite_url")
    is_active = data.get("is_active", True)
    
    if not wid:
        return jsonify(envelope(None, "Group ID missing", 400, False)), 400
        
    conn, cursor = db_connection()
    cursor.execute("UPDATE food_trade_whatsapp_groups SET invite_url = ?, is_active = ? WHERE id = ?", (invite_url, is_active, wid))
    conn.commit()
    conn.close()
    return jsonify(envelope({"ok": True}, "Whatsapp group updated", 200, True)), 200
