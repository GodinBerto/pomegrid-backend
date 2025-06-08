import sqlite3
from flask import Blueprint, request, jsonify
from flask_cors import CORS
from flask_jwt_extended import JWTManager, create_access_token, get_jwt, jwt_required, get_jwt_identity
from werkzeug.security import generate_password_hash, check_password_hash
from database import db_connection
from routes import response

# Initialize the Flask auth
auth = Blueprint('auth', __name__)

@auth.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    email = data.get('email')
    full_name = data.get('full_name')
    phone = data.get('phone')
    user_type = data.get('user_type')  # Should be 'farmer' or 'consumer'
    address = data.get('address')  # Optional
    profile_image_url = data.get('profile_image_url')  # Optional

    # Validate required fields
    if not all([username, password, email, full_name, phone, user_type]):
        return jsonify({'message': 'All required fields must be provided'}), 400

    if user_type not in ['farmer', 'consumer']:
        return jsonify({'message': 'Invalid user_type. Must be "farmer" or "consumer".'}), 400

    hashed_password = generate_password_hash(password)

    try:
        conn, cursor = db_connection()

        cursor.execute('''
            INSERT INTO Users (
                username, email, password_hash, full_name, phone,
                user_type, address, profile_image_url
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            username, email, hashed_password, full_name, phone,
            user_type, address, profile_image_url
        ))

        conn.commit()
        conn.close()

        return jsonify({'message': 'User registered successfully'}), 201

    except Exception as e:
        print("Registration error:", e)
        if 'UNIQUE constraint failed' in str(e):
            return jsonify({'message': 'Username or email already exists'}), 409
        return jsonify({'message': 'Internal server error'}), 500
    

@auth.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')

    if not email or not password:
        return jsonify({'message': 'Username and password are required'}), 400

    conn, cursor = db_connection()
    cursor.execute('SELECT id, username, password_hash, email, full_name, phone, user_type, address, is_admin, is_active FROM Users WHERE email = ?', (email,))
    user = cursor.fetchone()
    conn.close()

    if user is None:
        return jsonify(response({}, 'Incorrect email', 404)), 404

    # Unpack all values in the correct order
    (
        user_id, username, password_hash, email, full_name,
        phone, user_type, address, is_admin, is_active
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
        'is_active': is_active
    }
    access_token = create_access_token(identity=str(user_id))

    return jsonify({
        'access_token': access_token,
        'message': 'Login successful',
        'data': user_data,
        'status': 200
    }), 200


@auth.route('/protected', methods=['GET'])
@jwt_required()
def protected():
    current_user = get_jwt_identity()
    return jsonify({'message': f'Hello, {current_user["username"]}! This is a protected route.'}), 200

@auth.route('/get_token', methods=['GET'])
@jwt_required()
def get_token():
    session = request.environ.get('beaker.session')
    if session is None:
        return jsonify({'message': 'Session not found'}), 500
    current_user = get_jwt_identity()
    if not current_user:
        return jsonify({'message': 'User not authenticated'}), 401
    
    return jsonify({'token': current_user}), 200