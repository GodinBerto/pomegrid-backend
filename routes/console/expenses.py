import uuid
from datetime import datetime
from flask import request, jsonify
from flask_jwt_extended import jwt_required

from database import db_connection
from decorators.roles import get_authenticated_user_id
from routes.api_envelope import envelope
from . import console_bp


def generate_expense_number(cursor):
    cursor.execute("SELECT expense_number FROM Console_Expenses ORDER BY expense_number ASC LIMIT 1")
    row = cursor.fetchone()
    if row and row["expense_number"].startswith("EXP-"):
        try:
            num = int(row["expense_number"].split("-")[1])
            if num > 1:
                return f"EXP-{num - 1:06d}"
        except Exception:
            pass
    return "EXP-999999"


@console_bp.route("/expenses", methods=["POST"])
@jwt_required()
def create_expense():
    user_id = get_authenticated_user_id()
    data = request.get_json() or {}
    
    category_id = data.get("category_id")
    category_name = data.get("category_name")
    vendor_name = data.get("vendor_name")
    amount = data.get("amount", 0.0)
    description = data.get("description", "")
    expense_date = data.get("expense_date")
    status = data.get("status", "pending")
    
    if not expense_date:
        return jsonify(envelope(None, "expense_date is required", 400, False)), 400
        
    exp_id = str(uuid.uuid4())
    try:
        conn, cursor = db_connection()
        expense_number = generate_expense_number(cursor)
        
        cursor.execute(
            """
            INSERT INTO Console_Expenses (
                id, expense_number, category_id, category_name, vendor_name,
                amount, description, expense_date, status, created_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (exp_id, expense_number, category_id, category_name, vendor_name, amount, description, expense_date, status, user_id)
        )
        conn.commit()
        return jsonify(envelope({"id": exp_id, "category_name": category_name, "expense_number": expense_number}, "Expense created successfully", 201)), 201
    except Exception as e:
        return jsonify(envelope(None, str(e), 500, False)), 500


@console_bp.route("/expenses", methods=["GET"])
@jwt_required()
def get_expenses():
    try:
        conn, cursor = db_connection()
        cursor.execute("SELECT * FROM Console_Expenses ORDER BY created_at DESC")
        items = [dict(row) for row in cursor.fetchall()]
        
        # Calculate highest and lowest amount
        highest_amount = max([item["amount"] for item in items]) if items else 0.0
        lowest_amount = min([item["amount"] for item in items]) if items else 0.0
        
        meta = {
            "highest_amount": highest_amount,
            "lowest_amount": lowest_amount
        }
        
        return jsonify(envelope(items, "Expenses fetched successfully", 200, True, meta)), 200
    except Exception as e:
        return jsonify(envelope(None, str(e), 500, False)), 500


@console_bp.route("/expenses/<exp_id>", methods=["GET"])
@jwt_required()
def get_expense_by_id(exp_id):
    try:
        conn, cursor = db_connection()
        cursor.execute("SELECT * FROM Console_Expenses WHERE id = ?", (exp_id,))
        row = cursor.fetchone()
        if not row:
            return jsonify(envelope(None, "Expense not found", 404, False)), 404
        return jsonify(envelope(dict(row), "Expense fetched successfully")), 200
    except Exception as e:
        return jsonify(envelope(None, str(e), 500, False)), 500


@console_bp.route("/expenses/<exp_id>", methods=["PUT"])
@jwt_required()
def update_expense(exp_id):
    data = request.get_json() or {}
    
    try:
        conn, cursor = db_connection()
        
        updates = []
        params = []
        for key in ["category_id", "category_name", "vendor_name", "amount", "description", "expense_date", "status"]:
            if key in data:
                updates.append(f"{key} = ?")
                params.append(data[key])
                
        if not updates:
            return jsonify(envelope(None, "No valid fields to update", 400, False)), 400
            
        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(exp_id)
        
        query = f"UPDATE Console_Expenses SET {', '.join(updates)} WHERE id = ?"
        cursor.execute(query, params)
        if cursor.rowcount == 0:
            return jsonify(envelope(None, "Expense not found", 404, False)), 404
            
        conn.commit()
        return jsonify(envelope({"id": exp_id}, "Expense updated successfully")), 200
    except Exception as e:
        return jsonify(envelope(None, str(e), 500, False)), 500


@console_bp.route("/expenses/<exp_id>", methods=["DELETE"])
@jwt_required()
def delete_expense(exp_id):
    try:
        conn, cursor = db_connection()
        cursor.execute("DELETE FROM Console_Expenses WHERE id = ?", (exp_id,))
        if cursor.rowcount == 0:
            return jsonify(envelope(None, "Expense not found", 404, False)), 404
        conn.commit()
        return jsonify(envelope(None, "Expense deleted successfully")), 200
    except Exception as e:
        return jsonify(envelope(None, str(e), 500, False)), 500


@console_bp.route("/expenses/<exp_id>/status", methods=["POST"])
@jwt_required()
def update_expense_status(exp_id):
    user_id = get_authenticated_user_id()
    data = request.get_json() or {}
    status = data.get("status")
    
    if status not in ("pending", "paid", "rejected", "void"):
        return jsonify(envelope(None, "Invalid status", 400, False)), 400

    try:
        conn, cursor = db_connection()
        # The prompt says "for he created by use the user id from the token". I'll update created_by or maybe it just means for tracking the person who changed it? The schema has created_by, maybe they meant to update it or log it. I will update `created_by` to the current user as requested.
        cursor.execute(
            "UPDATE Console_Expenses SET status = ?, created_by = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", 
            (status, user_id, exp_id)
        )
        if cursor.rowcount == 0:
            return jsonify(envelope(None, "Expense not found", 404, False)), 404
        conn.commit()
        return jsonify(envelope({"id": exp_id, "status": status}, "Expense status updated successfully")), 200
    except Exception as e:
        return jsonify(envelope(None, str(e), 500, False)), 500
