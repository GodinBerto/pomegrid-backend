from flask import Flask
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from config import Config

#routes
from routes.users import users
from routes.authentication import auth
from routes.products import products
from routes.categories import categories
from routes.orders import orders
from routes.cart import carts

#Cloudinary
import cloudinary


app = Flask(__name__)

# Load configuration from the Config object
app.config.from_object(Config)
    
# Initialize JWT Manager
jwt = JWTManager(app)
app.config['JWT_SECRET_KEY'] = 'your_jwt_secret_key'  # Change this to a random secret key
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = 3600  # Token expires in 1 hour
app.config['JWT_REFRESH_TOKEN_EXPIRES'] = 86400  # Refresh token expires in 24 hours
app.config['JWT_TOKEN_LOCATION'] = ['headers', 'cookies']

cloudinary.config(
    cloud_name=app.config['CLOUDINARY_API_NAME'],
    api_key=app.config['CLOUDINARY_API_KEY'],
    api_secret=app.config['CLOUDINARY_API_SECRET']
)

CORS(app, supports_credentials=True, max_age=86400)

url = app.config['BASE_URL']

# Register blueprints
app.register_blueprint(auth, url_prefix=f'{url}/auth')
app.register_blueprint(products, url_prefix=f'{url}/products')
app.register_blueprint(categories, url_prefix=f'{url}/categories')
app.register_blueprint(users, url_prefix=f'{url}/users')
app.register_blueprint(orders, url_prefix=f'{url}/orders')
app.register_blueprint(carts, url_prefix=f'{url}/carts')


if __name__ == '__main__':
    # Create the app
    app.run(host='0.0.0.0', port=8000, debug=True)