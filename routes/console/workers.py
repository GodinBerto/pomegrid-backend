import uuid
from flask import request, jsonify
from flask_jwt_extended import jwt_required

from database import db_connection
from routes.api_envelope import envelope
from . import console_bp


@console_bp.route("/workers", methods=["POST"])
@jwt_required()
def create_worker():
    data = request.get_json() or {}
    
    full_name = data.get("full_name")
    role = data.get("role")
    status = data.get("status", "active")
    email = data.get("email")
    phone = data.get("phone")
    salary = data.get("salary", 0.0)
    joined_date = data.get("joined_date")
    
    if not full_name:
        return jsonify(envelope(None, "full_name is required", 400, False)), 400
    if not joined_date:
        return jsonify(envelope(None, "joined_date is required", 400, False)), 400
    if not role:
        return jsonify(envelope(None, "role is required", 400, False)), 400
        
    worker_id = str(uuid.uuid4())
    try:
        conn, cursor = db_connection()
        cursor.execute(
            """
            INSERT INTO Console_Workers (
                id, full_name, role, status, email, phone, salary, joined_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (worker_id, full_name, role, status, email, phone, salary, joined_date)
        )
        conn.commit()
        return jsonify(envelope({"id": worker_id, "full_name": full_name, "role": role, "joined_date": joined_date}, "Worker created successfully", 201)), 201
    except Exception as e:
        return jsonify(envelope(None, str(e), 500, False)), 500


@console_bp.route("/workers", methods=["GET"])
@jwt_required()
def get_workers():
    try:
        conn, cursor = db_connection()
        cursor.execute("SELECT * FROM Console_Workers ORDER BY created_at DESC")
        items = [dict(row) for row in cursor.fetchall()]
        return jsonify(envelope(items, "Workers fetched successfully")), 200
    except Exception as e:
        return jsonify(envelope(None, str(e), 500, False)), 500


@console_bp.route("/workers/<worker_id>", methods=["GET"])
@jwt_required()
def get_worker_by_id(worker_id):
    try:
        conn, cursor = db_connection()
        cursor.execute("SELECT * FROM Console_Workers WHERE id = ?", (worker_id,))
        row = cursor.fetchone()
        if not row:
            return jsonify(envelope(None, "Worker not found", 404, False)), 404
        return jsonify(envelope(dict(row), "Worker fetched successfully")), 200
    except Exception as e:
        return jsonify(envelope(None, str(e), 500, False)), 500


@console_bp.route("/workers/<worker_id>", methods=["PUT"])
@jwt_required()
def update_worker(worker_id):
    data = request.get_json() or {}
    
    try:
        conn, cursor = db_connection()
        updates = []
        params = []
        for key in ["full_name", "role", "status", "email", "phone", "salary", "joined_date", "left_date"]:
            if key in data:
                updates.append(f"{key} = ?")
                params.append(data[key])
                
        if not updates:
            return jsonify(envelope(None, "No valid fields to update", 400, False)), 400
            
        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(worker_id)
        
        query = f"UPDATE Console_Workers SET {', '.join(updates)} WHERE id = ?"
        cursor.execute(query, params)
        if cursor.rowcount == 0:
            return jsonify(envelope(None, "Worker not found", 404, False)), 404
            
        conn.commit()
        return jsonify(envelope({"id": worker_id}, "Worker updated successfully")), 200
    except Exception as e:
        return jsonify(envelope(None, str(e), 500, False)), 500


@console_bp.route("/workers/<worker_id>", methods=["DELETE"])
@jwt_required()
def delete_worker(worker_id):
    try:
        conn, cursor = db_connection()
        cursor.execute("DELETE FROM Console_Workers WHERE id = ?", (worker_id,))
        if cursor.rowcount == 0:
            return jsonify(envelope(None, "Worker not found", 404, False)), 404
        conn.commit()
        return jsonify(envelope(None, "Worker deleted successfully")), 200
    except Exception as e:
        return jsonify(envelope(None, str(e), 500, False)), 500
