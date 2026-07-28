from flask import jsonify
from flask_jwt_extended import jwt_required
from datetime import datetime, timedelta

from database import db_connection
from routes.api_envelope import envelope
from . import console_bp

@console_bp.route("/analytics", methods=["GET"])
@jwt_required()
def get_analytics():
    try:
        conn, cursor = db_connection()
        
        # We need data for the last 12 months for Budget Efficiency and Monthly Savings
        # For SQLite, we can just fetch all budgets and spendings and do it in Python
        cursor.execute("SELECT month, year, sum(budget_amount) as total FROM Console_Monthly_Budgets GROUP BY year, month")
        budgets_data = cursor.fetchall()
        
        # expenses grouped by YYYY-MM
        cursor.execute("SELECT substr(expense_date, 1, 7) as ym, sum(amount) as total FROM Console_Expenses WHERE status = 'paid' GROUP BY substr(expense_date, 1, 7)")
        expenses_data = cursor.fetchall()
        
        # Create a mapping of YYYY-MM to budget and actual
        monthly_map = {}
        for b in budgets_data:
            ym = f"{b['year']:04d}-{b['month']:02d}"
            monthly_map[ym] = {"budget": b["total"], "actual": 0.0}
            
        for e in expenses_data:
            ym = e["ym"]
            if ym not in monthly_map:
                monthly_map[ym] = {"budget": 0.0, "actual": 0.0}
            monthly_map[ym]["actual"] = e["total"]
            
        # Calculate Efficiency (on-target months)
        total_months = len(monthly_map)
        on_target = sum(1 for m in monthly_map.values() if m["actual"] <= m["budget"] and m["budget"] > 0)
        efficiency_pct = int((on_target / total_months) * 100) if total_months > 0 else 0
        
        efficiency_data = [
            {"name": "Efficiency", "value": efficiency_pct, "fill": "var(--color-chart-1)"}
        ]
        
        # Calculate Savings per month (sort by YYYY-MM)
        sorted_ym = sorted(monthly_map.keys())[-12:] # Last 12 months
        savings_data = []
        for ym in sorted_ym:
            month_name = datetime.strptime(ym, "%Y-%m").strftime("%b")
            m = monthly_map[ym]
            savings_data.append({
                "month": month_name,
                "budget": m["budget"],
                "actual": m["actual"]
            })
            
        # Category momentum
        cursor.execute("SELECT category_name as name, sum(amount) as value FROM Console_Expenses WHERE status = 'paid' GROUP BY category_name")
        categories_db = cursor.fetchall()
        colors = ["#3b82f6", "#10b981", "#f59e0b", "#8b5cf6", "#ec4899"]
        category_momentum = []
        for i, c in enumerate(categories_db):
            name = c["name"] or "Uncategorized"
            category_momentum.append({
                "name": name,
                "value": c["value"],
                "color": colors[i % len(colors)]
            })
            
        # Weekly rhythm
        cursor.execute("SELECT substr(expense_date, 9, 2) as day, sum(amount) as total FROM Console_Expenses WHERE status = 'paid' GROUP BY substr(expense_date, 9, 2) ORDER BY substr(expense_date, 9, 2) DESC LIMIT 7")
        weekly_db = cursor.fetchall()
        weekly_rhythm = []
        for w in reversed(weekly_db):
            weekly_rhythm.append({
                "day": w["day"],
                "spend": w["total"]
            })
            
        data = {
            "efficiency": efficiency_data,
            "savings": savings_data,
            "category_momentum": category_momentum,
            "weekly_rhythm": weekly_rhythm
        }
        
        return jsonify(envelope(data, "Analytics fetched successfully")), 200
        
    except Exception as e:
        return jsonify(envelope(None, str(e), 500, False)), 500
