from flask import Blueprint

food_trade_api = Blueprint("food_trade_api", __name__)

from . import categories, products, orders, whatsapp, admin, auth, weekly_products, payments, cart
