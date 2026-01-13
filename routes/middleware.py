from flask import Blueprint
from middleware.authMiddleware import auth_middleware

api_bp = Blueprint("api", __name__, url_prefix="/api")

@api_bp.before_request
def before_api_request():
    return auth_middleware()
