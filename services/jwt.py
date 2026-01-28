from flask_jwt_extended import JWTManager
from services.token_service import is_token_revoked

jwt = JWTManager()

# @jwt.token_in_blocklist_loader
# def check_if_token_revoked(jwt_header, jwt_payload):
#     return is_token_revoked(jwt_payload["jti"])
