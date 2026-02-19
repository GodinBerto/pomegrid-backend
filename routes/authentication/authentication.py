import sqlite3
import logging
from flask import Blueprint, request, jsonify
from flask_cors import CORS
from flask_jwt_extended import create_access_token, create_refresh_token, get_csrf_token, get_jwt, jwt_required, get_jwt_identity, set_refresh_cookies, unset_jwt_cookies, verify_jwt_in_request
from werkzeug.security import generate_password_hash, check_password_hash
from database import db_connection
from extensions.redis_client import get_redis_client
from routes import response
from services.token_service import revoke_token
from config import Config

# Initialize the Flask auth
auth = Blueprint('auth', __name__)
logger = logging.getLogger(__name__)

ALLOWED_USER_TYPES = {
    "user",
    "farmer",
    "worker",
    "admin",
    "super admin",
}
PUBLIC_REGISTRATION_USER_TYPES = {"user", "farmer", "worker"}


def normalize_user_type(value, default_value="user"):
    if value is None:
        return default_value

    normalized = str(value).strip().lower()
    aliases = {
        "consumer": "user",
        "normal-consumer-user": "user",
        "normal_consumer_user": "user",
        "normal consumer user": "user",
        "superadmin": "super admin",
    }
    normalized = aliases.get(normalized, normalized)
    return normalized

@auth.route('/register', methods=['POST'])
def register():
    data = request.get_json() or {}
    username = data.get('username')
    password = data.get('password')
    email = data.get('email')
    full_name = data.get('full_name')
    phone = data.get('phone')
    user_type = normalize_user_type(data.get('user_type', "user"))
    address = data.get('address')  # Optional
    profile_image_url = data.get('profile_image_url')  # Optional
    date_of_birth = data.get('date_of_birth')  # Optional

    # Validate required fields
    if not all([username, password, email, full_name, phone, user_type, date_of_birth]):
        return jsonify({'message': 'All required fields must be provided'}), 400

    if user_type not in ALLOWED_USER_TYPES:
        return jsonify({'message': 'Invalid user_type.'}), 400
    if user_type not in PUBLIC_REGISTRATION_USER_TYPES:
        return jsonify({'message': 'Only user, farmer, or worker can self-register.'}), 403
    
    # Check if username or email already exists 
    conn, cursor = db_connection()
    cursor.execute('SELECT id FROM Users WHERE username = ? OR email = ?', (username, email))
    existing_user = cursor.fetchone()
    conn.close()
    if existing_user:
        return jsonify({'message': 'Username or email already exists'}), 409

    hashed_password = generate_password_hash(password)

    try:
        conn, cursor = db_connection()

        cursor.execute('''
            INSERT INTO Users (
                username, email, password_hash, full_name, phone,
                user_type, address, profile_image_url, date_of_birth
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            username, email, hashed_password, full_name, phone,
            user_type, address, profile_image_url, date_of_birth
        ))

        conn.commit()
        conn.close()

        return jsonify(response([], "User registered successfully", 200)), 201

    except Exception as e:
        logger.exception("Registration error")
        if 'UNIQUE constraint failed' in str(e):
            return jsonify({'message': 'Username or email already exists'}), 409
        return jsonify({'message': 'Internal server error'}), 500


@auth.route('/register-admin', methods=['POST'])
def register_admin():
    data = request.get_json() or {}
    admin_setup_key = data.get("admin_setup_key")
    if admin_setup_key != Config.ADMIN_SETUP_KEY:
        return jsonify(response(None, "Invalid admin setup key", 403)), 403

    username = data.get('username')
    password = data.get('password')
    email = data.get('email')
    full_name = data.get('full_name')
    phone = data.get('phone')
    date_of_birth = data.get('date_of_birth')
    address = data.get('address')
    profile_image_url = data.get('profile_image_url')
    user_type = normalize_user_type(data.get("user_type", "admin"), "admin")

    if not all([username, password, email, full_name, phone, date_of_birth]):
        return jsonify(response(None, "All required fields must be provided", 400)), 400
    if user_type not in {"admin", "super admin"}:
        return jsonify(response(None, 'user_type must be "admin" or "super admin"', 400)), 400

    hashed_password = generate_password_hash(password)
    try:
        conn, cursor = db_connection()
        cursor.execute(
            """
            INSERT INTO Users (
                username, email, password_hash, full_name, phone,
                user_type, address, profile_image_url, date_of_birth, is_admin
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                username,
                email,
                hashed_password,
                full_name,
                phone,
                user_type,
                address,
                profile_image_url,
                date_of_birth,
                1,
            ),
        )
        user_id = cursor.lastrowid
        cursor.execute("INSERT OR IGNORE INTO Admins (user_id) VALUES (?)", (user_id,))
        conn.commit()
        conn.close()
        return jsonify(response({"user_id": user_id}, "Admin registered successfully", 201)), 201
    except Exception as e:
        logger.exception("Admin registration error")
        if 'UNIQUE constraint failed' in str(e):
            return jsonify({'message': 'Username or email already exists'}), 409
        return jsonify({'message': 'Internal server error'}), 500
    

@auth.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')

    if not email or not password:
        return jsonify(response({}, "Username and password are required", 400)), 400

    conn, cursor = db_connection()
    cursor.execute('SELECT id, username, password_hash, email, full_name, phone, user_type, address, is_admin, is_active, date_of_birth FROM Users WHERE email = ?', (email,))
    user = cursor.fetchone()
    conn.close()

    if user is None:
        return jsonify(response({}, 'Incorrect email', 404)), 401

    # Unpack all values in the correct order
    (
        user_id, username, password_hash, email, full_name,
        phone, user_type, address, is_admin, is_active, date_of_birth
    ) = user

    if not check_password_hash(password_hash, password):
        return jsonify(response({}, 'Incorrect password', 401)), 401
        
    user_data = {
        'id': user_id,
        'username': username,
        'email': email,
        'full_name': full_name,
        'phone': phone,
        'user_type': user_type,
        'address': address,
        'is_admin': is_admin,
        'is_active': is_active,
        'date_of_birth': date_of_birth}
    
    access_token = create_access_token(identity=str(user_id))
    refresh_token = create_refresh_token(identity=str(user_id))
   
   # Prepare the response data
    res = {
        'access_token': access_token,  # frontend stores 
        'csrf_token': get_csrf_token(refresh_token),  # ⭐ important
        'data': user_data,
    }

    # Create a Flask Response object
    resp = jsonify(response(res, "Login Successful", 200))
    
    set_refresh_cookies(resp, refresh_token)
    
    return resp, 200


@auth.route("/logout", methods=["POST"])
@jwt_required()  # ✅ uses access token instead of refresh
def logout():
    jti = get_jwt()["jti"]  # get the unique token ID
    expires = get_jwt()["exp"] - get_jwt()["iat"]  # remaining lifetime

    # Revoke the access token
    revoke_token(jti, expires)

    # Clear JWT cookies if any
    resp = jsonify({"message": "Logged out"})
    unset_jwt_cookies(resp)  # optional, clears cookies if set

    return resp, 200


@auth.route('/protected', methods=['GET'])
@jwt_required()
def protected():
    current_user = get_jwt_identity()
    return jsonify({'message': f'Hello, {current_user["username"]}! This is a protected route.'}), 200


@auth.route("/refresh", methods=["POST"])
@jwt_required(refresh=True)
def refresh():
    jwt_data = get_jwt()
    user_id = get_jwt_identity()
    refresh_jti = jwt_data.get("jti")
    expires_in = jwt_data.get("exp", 0) - jwt_data.get("iat", 0)

    refresh_reused = False
    try:
        redis_client = get_redis_client()
        used_key = f"refresh_used:{refresh_jti}"
        refresh_reused = redis_client.exists(used_key) == 1
        if not refresh_reused and expires_in > 0:
            redis_client.setex(used_key, expires_in, "true")
    except Exception as e:
        logger.warning("Redis unavailable, skipping refresh reuse check: %s", e)

    new_access = create_access_token(identity=user_id)
    new_refresh = create_refresh_token(identity=user_id)
    new_csrf = get_csrf_token(new_refresh)

    payload = {
        "access_token": new_access,
        "csrf_token": new_csrf,
    }
    if refresh_reused:
        payload["message"] = "Refresh token already used. We rotated your refresh token; please retry with the new CSRF token."
        payload["requires_retry"] = True

    resp = jsonify(payload)
    set_refresh_cookies(resp, new_refresh)

    return resp, 200
