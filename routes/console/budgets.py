import uuid
from datetime import datetime
from flask import request, jsonify
from flask_jwt_extended import jwt_required

from database import db_connection
from routes.api_envelope import envelope
from . import console_bp


@console_bp.route("/monthly-budgets", methods=["POST"])
@jwt_required()
def create_monthly_budget():
    data = request.get_json() or {}
    
    year = data.get("year")
    month = data.get("month")
    budget_amount = data.get("budget_amount", 0.0)
    
    if year is None or month is None:
        now = datetime.now()
        year = now.year
        month = now.month
        
    try:
        conn, cursor = db_connection()
        cursor.execute("SELECT id FROM Console_Monthly_Budgets WHERE year = ? AND month = ?", (year, month))
        row = cursor.fetchone()
        
        if row:
            budget_id = row["id"]
            cursor.execute(
                "UPDATE Console_Monthly_Budgets SET budget_amount = ? WHERE id = ?",
                (budget_amount, budget_id)
            )
            msg = "Monthly budget updated successfully"
            status_code = 200
        else:
            budget_id = str(uuid.uuid4())
            cursor.execute(
                """
                INSERT INTO Console_Monthly_Budgets (id, year, month, budget_amount)
                VALUES (?, ?, ?, ?)
                """,
                (budget_id, year, month, budget_amount)
            )
            msg = "Monthly budget created successfully"
            status_code = 201
            
        conn.commit()
        return jsonify(envelope({"id": budget_id}, msg, status_code)), status_code
    except Exception as e:
        return jsonify(envelope(None, str(e), 500, False)), 500


@console_bp.route("/monthly-budgets", methods=["GET"])
@jwt_required()
def get_monthly_budgets():
    try:
        conn, cursor = db_connection()
        cursor.execute("SELECT * FROM Console_Monthly_Budgets ORDER BY year DESC, month DESC")
        items = [dict(row) for row in cursor.fetchall()]
        return jsonify(envelope(items, "Monthly budgets fetched successfully")), 200
    except Exception as e:
        return jsonify(envelope(None, str(e), 500, False)), 500


@console_bp.route("/monthly-budgets/<budget_id>", methods=["GET"])
@jwt_required()
def get_monthly_budget_by_id(budget_id):
    try:
        conn, cursor = db_connection()
        cursor.execute("SELECT * FROM Console_Monthly_Budgets WHERE id = ?", (budget_id,))
        row = cursor.fetchone()
        if not row:
            return jsonify(envelope(None, "Monthly budget not found", 404, False)), 404
        return jsonify(envelope(dict(row), "Monthly budget fetched successfully")), 200
    except Exception as e:
        return jsonify(envelope(None, str(e), 500, False)), 500


