from flask import Flask
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
from routes.user.user import users

#Routes Artisans
from routes.artisans.workers import workers
from routes.artisans.jobs import jobs
from routes.artisans.admins import admins

#Cloudinary
import cloudinary


# Initialize flask
app = Flask(__name__)

# Load configuration from the Config object
app.config.from_object(Config)

# ================================
# JWT CONFIGURATION
# ================================
app.config.update({
    "JWT_SECRET_KEY": Config.JWT_SECRET_KEY,
    "JWT_ACCESS_TOKEN_EXPIRES": timedelta(minutes=5),
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
    origins=["http://localhost:3000"]
)

setup_logging(app)


# Load Base URL from config.py
url = app.config['BASE_URL']

# Register blueprints
app.register_blueprint(auth, url_prefix=f'{url}/auth')
app.register_blueprint(products, url_prefix=f'{url}/products')
app.register_blueprint(categories, url_prefix=f'{url}/categories')
app.register_blueprint(users, url_prefix=f'{url}/users')
app.register_blueprint(orders, url_prefix=f'{url}/orders')
app.register_blueprint(carts, url_prefix=f'{url}/carts')

# Workers Blueprints
app.register_blueprint(workers, url_prefix=f"{url}/workers")
app.register_blueprint(jobs, url_prefix=f"{url}/jobs")
app.register_blueprint(admins, url_prefix=f"{url}/admins")

if __name__ == '__main__':
    # Create the app
    app.run(host='0.0.0.0', port=8000, debug=True)
