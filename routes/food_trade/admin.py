from flask import jsonify
from flask_jwt_extended import jwt_required

from middleware.authMiddleware import get_authenticated_user_id
from routes.api_envelope import envelope
from . import food_trade_api
from .utils import check_admin


@food_trade_api.route("/admin/is-admin", methods=["GET"])
@jwt_required()
def is_admin_check():
    user_id = get_authenticated_user_id()
    is_admin = check_admin(user_id) if user_id else False
    return jsonify(envelope({"isAdmin": is_admin}, "Admin status checked", 200, True)), 200
