from flask import request

from middleware.authMiddleware import auth_middleware


def protect_blueprint(blueprint, *allowed_roles, exempt_endpoints=None, require_active=True):
    exempt = {str(endpoint).strip() for endpoint in (exempt_endpoints or set()) if str(endpoint).strip()}

    @blueprint.before_request
    def _before_blueprint_request():
        # Let Flask/CORS handle browser preflight requests without forcing JWT auth.
        if request.method == "OPTIONS":
            return None

        endpoint = request.endpoint or ""
        endpoint_name = endpoint.rsplit(".", 1)[-1] if endpoint else ""
        if endpoint in exempt or endpoint_name in exempt:
            return None
        return auth_middleware(*allowed_roles, require_active=require_active)

    return blueprint
