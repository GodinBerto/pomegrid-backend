from flask_jwt_extended import JWTManager
from services.token_service import is_token_revoked
from routes.api_envelope import envelope

jwt = JWTManager()

@jwt.token_in_blocklist_loader
def check_if_token_revoked(jwt_header, jwt_payload):
    return is_token_revoked(jwt_payload.get("jti"))


@jwt.unauthorized_loader
def jwt_unauthorized(reason):
    return envelope(None, reason or "Missing authorization", 401, False), 401


@jwt.invalid_token_loader
def jwt_invalid_token(reason):
    return envelope(None, reason or "Invalid token", 422, False), 422


@jwt.expired_token_loader
def jwt_expired_token(jwt_header, jwt_payload):
    return envelope(None, "Token has expired", 401, False), 401


@jwt.revoked_token_loader
def jwt_revoked_token(jwt_header, jwt_payload):
    return envelope(None, "Token has been revoked", 401, False), 401


@jwt.needs_fresh_token_loader
def jwt_needs_fresh(jwt_header, jwt_payload):
    return envelope(None, "Fresh token required", 401, False), 401
