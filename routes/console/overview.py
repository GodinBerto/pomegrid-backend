from flask import jsonify
from flask_jwt_extended import jwt_required

from database import db_connection
from routes.api_envelope import envelope
from . import console_bp


@console_bp.route("/overview", methods=["GET"])
@jwt_required()
def get_overview():
    try:
        conn, cursor = db_connection()
        
        # This is a mocked or simplified overview logic. 
        # In a real scenario, you'd calculate exact previous month vs current month diffs.
        # Monthly budget
        cursor.execute("SELECT sum(budget_amount) as total FROM Console_Monthly_Budgets")
        budget_row = cursor.fetchone()
        budget = budget_row["total"] if budget_row and budget_row["total"] else 0.0
        
        # Spent this month
        cursor.execute("SELECT sum(amount) as total FROM Console_Expenses WHERE status = 'paid'")
        spent_row = cursor.fetchone()
        spent = spent_row["total"] if spent_row and spent_row["total"] else 0.0
        
        # Active workers
        cursor.execute("SELECT count(*) as total FROM Console_Workers WHERE status = 'active'")
        workers_row = cursor.fetchone()
        active_workers = workers_row["total"] if workers_row and workers_row["total"] else 0

        remaining = budget - spent
        
        data = {
            "monthly_budget": {
                "value": budget,
                "percentage_change": 5.0 # Mock percentage
            },
            "spent_this_month": {
                "value": spent,
                "percentage_change": 2.0
            },
            "remaining_budget": {
                "value": remaining,
                "percentage_change": -1.0
            },
            "active_workers": {
                "value": active_workers,
                "number_change": 2
            }
        }
        
        return jsonify(envelope(data, "Overview fetched successfully")), 200
    except Exception as e:
        return jsonify(envelope(None, str(e), 500, False)), 500


@console_bp.route("/overview-budget-chart", methods=["GET"])
@jwt_required()
def get_overview_budget_chart():
    try:
        conn, cursor = db_connection()
        
        cursor.execute("SELECT month, sum(budget_amount) as total FROM Console_Monthly_Budgets GROUP BY month")
        budgets = [{"x": row["month"], "y": row["total"]} for row in cursor.fetchall()]
        
        # Simple grouping by month from expense_date
        # Note: SQLite date extraction can be specific. We'll extract month using substr if it's YYYY-MM-DD
        cursor.execute("SELECT substr(expense_date, 6, 2) as month, sum(amount) as total FROM Console_Expenses GROUP BY substr(expense_date, 6, 2)")
        spendings = [{"x": int(row["month"]), "y": row["total"]} for row in cursor.fetchall() if row["month"]]
        
        data = {
            "budget_chart": budgets,
            "actual_spend": spendings
        }
        return jsonify(envelope(data, "Overview budget chart fetched")), 200
    except Exception as e:
        return jsonify(envelope(None, str(e), 500, False)), 500


@console_bp.route("/recent-expenses", methods=["GET"])
@jwt_required()
def get_recent_expenses():
    try:
        conn, cursor = db_connection()
        cursor.execute("SELECT * FROM Console_Expenses ORDER BY created_at DESC LIMIT 5")
        items = [dict(row) for row in cursor.fetchall()]
        return jsonify(envelope(items, "Recent expenses fetched")), 200
    except Exception as e:
        return jsonify(envelope(None, str(e), 500, False)), 500


@console_bp.route("/weekly-burn-chart", methods=["GET"])
@jwt_required()
def get_weekly_burn_chart():
    try:
        conn, cursor = db_connection()
        # Grouping by day (last 7 days usually, or just day of month)
        cursor.execute("SELECT substr(expense_date, 9, 2) as day, sum(amount) as total FROM Console_Expenses GROUP BY substr(expense_date, 9, 2) ORDER BY substr(expense_date, 9, 2) DESC LIMIT 7")
        items = [{"x": row["day"], "y": row["total"]} for row in cursor.fetchall() if row["day"]]
        # Reverse to show chronological order
        items.reverse()
        return jsonify(envelope(items, "Weekly burn chart fetched")), 200
    except Exception as e:
        return jsonify(envelope(None, str(e), 500, False)), 500
