import uuid
import csv
from io import StringIO
from flask import request, jsonify, make_response
from flask_jwt_extended import jwt_required

from database import db_connection
from decorators.roles import get_authenticated_user_id
from routes.api_envelope import envelope
from . import console_bp


# --- Expense Reports CRUD ---

@console_bp.route("/expense-reports", methods=["POST"])
@jwt_required()
def create_expense_report():
    user_id = get_authenticated_user_id()
    data = request.get_json() or {}
    title = data.get("title")
    report_type = data.get("report_type", "summary")
    file_url = data.get("file_url")
    
    if not title:
        return jsonify(envelope(None, "title is required", 400, False)), 400
        
    report_id = str(uuid.uuid4())
    try:
        conn, cursor = db_connection()
        cursor.execute(
            """
            INSERT INTO Console_Expense_Reports (id, title, report_type, generated_by, file_url)
            VALUES (?, ?, ?, ?, ?)
            """,
            (report_id, title, report_type, user_id, file_url)
        )
        conn.commit()
        return jsonify(envelope({"id": report_id}, "Expense report created successfully", 201)), 201
    except Exception as e:
        return jsonify(envelope(None, str(e), 500, False)), 500

@console_bp.route("/expense-reports", methods=["GET"])
@jwt_required()
def get_expense_reports():
    try:
        conn, cursor = db_connection()
        cursor.execute("SELECT * FROM Console_Expense_Reports ORDER BY generated_at DESC")
        items = [dict(row) for row in cursor.fetchall()]
        return jsonify(envelope(items, "Expense reports fetched successfully")), 200
    except Exception as e:
        return jsonify(envelope(None, str(e), 500, False)), 500

@console_bp.route("/expense-reports/<report_id>", methods=["GET"])
@jwt_required()
def get_expense_report_by_id(report_id):
    try:
        conn, cursor = db_connection()
        cursor.execute("SELECT * FROM Console_Expense_Reports WHERE id = ?", (report_id,))
        row = cursor.fetchone()
        if not row:
            return jsonify(envelope(None, "Expense report not found", 404, False)), 404
        return jsonify(envelope(dict(row), "Expense report fetched successfully")), 200
    except Exception as e:
        return jsonify(envelope(None, str(e), 500, False)), 500

@console_bp.route("/expense-reports/<report_id>", methods=["PUT"])
@jwt_required()
def update_expense_report(report_id):
    data = request.get_json() or {}
    
    try:
        conn, cursor = db_connection()
        updates = []
        params = []
        for key in ["title", "report_type", "file_url"]:
            if key in data:
                updates.append(f"{key} = ?")
                params.append(data[key])
                
        if not updates:
            return jsonify(envelope(None, "No valid fields to update", 400, False)), 400
            
        params.append(report_id)
        query = f"UPDATE Console_Expense_Reports SET {', '.join(updates)} WHERE id = ?"
        cursor.execute(query, params)
        if cursor.rowcount == 0:
            return jsonify(envelope(None, "Expense report not found", 404, False)), 404
            
        conn.commit()
        return jsonify(envelope({"id": report_id}, "Expense report updated successfully")), 200
    except Exception as e:
        return jsonify(envelope(None, str(e), 500, False)), 500

@console_bp.route("/expense-reports/<report_id>", methods=["DELETE"])
@jwt_required()
def delete_expense_report(report_id):
    try:
        conn, cursor = db_connection()
        cursor.execute("DELETE FROM Console_Expense_Reports WHERE id = ?", (report_id,))
        if cursor.rowcount == 0:
            return jsonify(envelope(None, "Expense report not found", 404, False)), 404
        conn.commit()
        return jsonify(envelope(None, "Expense report deleted successfully")), 200
    except Exception as e:
        return jsonify(envelope(None, str(e), 500, False)), 500


# --- Specific Business Reports ---

@console_bp.route("/reports", methods=["GET"])
@jwt_required()
def get_all_reports():
    # Return list of generated reports from DB or mock list
    return get_expense_reports()


@console_bp.route("/reports/<report_id>", methods=["GET"])
@jwt_required()
def get_report_by_id(report_id):
    return get_expense_report_by_id(report_id)


@console_bp.route("/reports/<report_id>/download", methods=["GET"])
@jwt_required()
def download_report(report_id):
    return jsonify(envelope(None, "Download link generated (mock)")), 200


@console_bp.route("/reports/<report_id>/print", methods=["GET"])
@jwt_required()
def print_report_id(report_id):
    return jsonify(envelope(None, "Print view generated (mock)")), 200


@console_bp.route("/reports/monthly-expense-summary", methods=["GET"])
@jwt_required()
def report_monthly_expense_summary():
    return jsonify(envelope([], "Monthly expense summary fetched")), 200

@console_bp.route("/reports/payroll-register", methods=["GET"])
@jwt_required()
def report_payroll_register():
    return jsonify(envelope([], "Payroll register fetched")), 200

@console_bp.route("/reports/budget-vs-actual", methods=["GET"])
@jwt_required()
def report_budget_vs_actual():
    return jsonify(envelope([], "Budget vs actual fetched")), 200

@console_bp.route("/reports/vendor-spend", methods=["GET"])
@jwt_required()
def report_vendor_spend():
    return jsonify(envelope([], "Vendor spend fetched")), 200

@console_bp.route("/reports/cash-burn", methods=["GET"])
@jwt_required()
def report_cash_burn():
    return jsonify(envelope([], "Cash burn fetched")), 200

@console_bp.route("/reports/tax-ready-ledger", methods=["GET"])
@jwt_required()
def report_tax_ready_ledger():
    return jsonify(envelope([], "Tax ready ledger fetched")), 200


@console_bp.route("/reports/pdf", methods=["GET"])
@jwt_required()
def report_pdf():
    return jsonify(envelope(None, "PDF generation not fully implemented yet", 200, True)), 200


@console_bp.route("/reports/csv", methods=["GET"])
@jwt_required()
def report_csv():
    try:
        conn, cursor = db_connection()
        cursor.execute("SELECT * FROM Console_Expenses")
        expenses = [dict(row) for row in cursor.fetchall()]
        
        si = StringIO()
        if expenses:
            keys = expenses[0].keys()
            writer = csv.DictWriter(si, fieldnames=keys)
            writer.writeheader()
            writer.writerows(expenses)
            
        output = make_response(si.getvalue())
        output.headers["Content-Disposition"] = "attachment; filename=report.csv"
        output.headers["Content-type"] = "text/csv"
        return output
    except Exception as e:
        return jsonify(envelope(None, str(e), 500, False)), 500


@console_bp.route("/reports/print", methods=["GET"])
@jwt_required()
def report_print():
    return jsonify(envelope(None, "Printable HTML version not fully implemented yet", 200, True)), 200
