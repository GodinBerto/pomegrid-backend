import os
from urllib.parse import urlsplit

from flask import Flask, jsonify, request
from flask_cors import CORS
from config import Config
from datetime import timedelta
from services.jwt import jwt 
from services.logging_service import setup_logging

#Routes Auth
from routes.authentication.authentication import auth

#Routes Farms
from routes.farms.products import products
from routes.farms.categories import categories
from routes.farms.orders import orders
from routes.farms.cart import carts
from routes.farms.services import farm_services
from routes.farms.admin.product import products_admin
from routes.farms.admin.category import categories_admin
from routes.farms.admin.order import orders_admin
from routes.farms.admin.messages import farms_admin_messages_api
from routes.payments_api import payments
from routes.user.user import users
from routes.user.support_messages import user_support_api

#Routes Artisans
from routes.artisans.workers import workers
from routes.artisans.jobs import jobs
from routes.artisans.admin.admins import admins
from routes.artisans.bookings import bookings
from routes.artisans.admin.workers import workers_admin
from routes.artisans.admin.bookings import bookings_admin
from routes.artisans.admin.dashboard import admin_api
from routes.artisans.worker.dashboard import worker_api
from extensions.socketio import register_socket_handlers, socketio

#Cloudinary
import cloudinary


# Initialize flask
app = Flask(__name__)

# Load configuration from the Config object
app.config.from_object(Config)


DEFAULT_FRONTEND_ORIGINS = (
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8080",
    "http://127.0.0.1:8080",
    "http://pomegrid.pythonanywhere.com",
    "https://pomegrid.pythonanywhere.com",
)


def _normalize_origin(value):
    origin = str(value or "").strip().rstrip("/")
    if not origin:
        return None

    if "://" not in origin:
        origin = f"https://{origin}"

    parsed = urlsplit(origin)
    scheme = (parsed.scheme or "").strip().lower()
    host = (parsed.hostname or "").strip().lower()
    if scheme not in {"http", "https"} or not host:
        return None

    port = f":{parsed.port}" if parsed.port else ""
    return f"{scheme}://{host}{port}"


def _get_allowed_frontend_origins():
    origins = []
    seen = set()

    def add_origin(value):
        origin = _normalize_origin(value)
        if origin and origin not in seen:
            origins.append(origin)
            seen.add(origin)

    for item in DEFAULT_FRONTEND_ORIGINS:
        add_origin(item)

    raw_origins = os.getenv("FRONTEND_ALLOWED_ORIGINS", "")
    for item in raw_origins.split(","):
        add_origin(item)

    for origin in list(origins):
        parsed = urlsplit(origin)
        host = (parsed.hostname or "").strip().lower()
        if host not in {"localhost", "127.0.0.1"}:
            continue

        sibling_host = "127.0.0.1" if host == "localhost" else "localhost"
        port = f":{parsed.port}" if parsed.port else ""
        sibling_origin = f"{parsed.scheme}://{sibling_host}{port}"
        add_origin(sibling_origin)
    return origins


ALLOWED_FRONTEND_ORIGINS = _get_allowed_frontend_origins()

# ================================
# JWT CONFIGURATION
# ================================
app.config.update({
    "JWT_SECRET_KEY": Config.JWT_SECRET_KEY,
    "JWT_ACCESS_TOKEN_EXPIRES": timedelta(minutes=1000),
    "JWT_REFRESH_TOKEN_EXPIRES": timedelta(days=7),
    "JWT_ACCESS_COOKIE_NAME": "access_token_cookie",
    "JWT_TOKEN_LOCATION": ["headers", "cookies"],
    "JWT_REFRESH_COOKIE_NAME": "refresh_token",
    "JWT_COOKIE_SECURE": True,
    "JWT_COOKIE_SAMESITE": "None",  # ✅ best balance
    "JWT_COOKIE_CSRF_PROTECT": True,
})
    
# Initialize JWT Manager
jwt.init_app(app)

# Cloudinary Configuration
cloudinary.config(
    cloud_name=app.config['CLOUDINARY_API_NAME'],
    api_key=app.config['CLOUDINARY_API_KEY'],
    api_secret=app.config['CLOUDINARY_API_SECRET']
)

CORS(
    app,
    supports_credentials=True,
    origins=ALLOWED_FRONTEND_ORIGINS
)

socketio.init_app(
    app,
    cors_allowed_origins=ALLOWED_FRONTEND_ORIGINS,
)
register_socket_handlers()

setup_logging(app)


# Load Base URL from config.py
url = app.config['BASE_URL']
API_ROOT_ETAG = "pomegrid-api-root-v1"


def _build_api_root_response():
    response = jsonify({
        "message": "Pomegrid API is running",
        "base_url": url,
        "api_root": url,
    })
    response.headers["Cache-Control"] = "public, max-age=3600, stale-while-revalidate=60"
    response.set_etag(API_ROOT_ETAG)
    response.make_conditional(request)
    return response


@app.route("/", methods=["GET"])
def service_root():
    return _build_api_root_response()


@app.route(url, methods=["GET"])
@app.route(f"{url}/", methods=["GET"])
def api_root():
    return _build_api_root_response()

# Register blueprints
app.register_blueprint(auth, url_prefix=f'{url}/auth')
app.register_blueprint(products, url_prefix=f'{url}/products')
app.register_blueprint(categories, url_prefix=f'{url}/categories')
app.register_blueprint(payments, url_prefix=f'{url}/payments')
app.register_blueprint(users, url_prefix=f'{url}/users')
app.register_blueprint(user_support_api, url_prefix=f'{url}/user')
app.register_blueprint(orders, url_prefix=f'{url}/orders')
app.register_blueprint(carts, url_prefix=f'{url}/carts')
app.register_blueprint(farm_services, url_prefix=f'{url}/services')
app.register_blueprint(products_admin, url_prefix=f'{url}/products')
app.register_blueprint(categories_admin, url_prefix=f'{url}/categories')
app.register_blueprint(orders_admin, url_prefix=f'{url}/orders')
app.register_blueprint(farms_admin_messages_api, url_prefix=f'{url}/admin')

# Workers Blueprints
app.register_blueprint(workers, url_prefix=f"{url}/workers")
app.register_blueprint(workers_admin, url_prefix=f"{url}/workers")
app.register_blueprint(jobs, url_prefix=f"{url}/jobs")
app.register_blueprint(admins, url_prefix=f"{url}/admins")
app.register_blueprint(bookings, url_prefix=f"{url}")
app.register_blueprint(bookings_admin, url_prefix=f"{url}")
app.register_blueprint(admin_api, url_prefix=f"{url}/admin")
app.register_blueprint(worker_api, url_prefix=f"{url}/worker")

if __name__ == '__main__':
    # Create the app
    socketio.run(app, host='0.0.0.0', port=8000, debug=True)
