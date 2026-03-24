from flask import jsonify

from database import db_connection
from routes.api_envelope import envelope

from .common import (
    _current_previous_month_bounds,
    _current_user_id,
    _direction_for_change,
    _format_currency,
    _format_signed_count,
    _format_signed_percent,
    _month_key,
    _month_series,
    _normalize_account_type,
    _percent_change,
    connect_api,
    logger,
)
from .orders import _build_farmer_order_summary, _build_importer_order_summary
from .profiles import _require_connect_profile


@connect_api.route("/dashboard/overview", methods=["GET"])
def get_connect_dashboard_overview():
    user_id = _current_user_id()
    current_month_start, previous_month_start = _current_previous_month_bounds()
    months = _month_series()
    oldest_month_start = months[0]["start"]

    try:
        conn, cursor = db_connection()
        profile_row = _require_connect_profile(cursor, user_id)
        if not profile_row:
            conn.close()
            return jsonify(envelope(None, "Connect profile not found", 404, False)), 404

        account_type = _normalize_account_type(profile_row["account_type"])
        if account_type == "farmer":
            cursor.execute("SELECT COUNT(*) AS total FROM Products WHERE user_id = ? AND COALESCE(is_active, 1) = 1", (user_id,))
            total_listings = int(cursor.fetchone()["total"] or 0)
            cursor.execute("SELECT COUNT(*) AS total FROM Products WHERE user_id = ? AND COALESCE(is_active, 1) = 1 AND created_at >= ?", (user_id, current_month_start))
            current_listings = int(cursor.fetchone()["total"] or 0)
            cursor.execute("SELECT COUNT(*) AS total FROM Products WHERE user_id = ? AND COALESCE(is_active, 1) = 1 AND created_at >= ? AND created_at < ?", (user_id, previous_month_start, current_month_start))
            previous_listings = int(cursor.fetchone()["total"] or 0)

            cursor.execute(
                """
                SELECT COUNT(DISTINCT o.id) AS total
                FROM Orders o
                JOIN OrderItems oi ON oi.order_id = o.id
                JOIN Products p ON p.id = oi.product_id
                WHERE p.user_id = ?
                """,
                (user_id,),
            )
            total_orders = int(cursor.fetchone()["total"] or 0)
            cursor.execute(
                """
                SELECT COUNT(DISTINCT o.id) AS total
                FROM Orders o
                JOIN OrderItems oi ON oi.order_id = o.id
                JOIN Products p ON p.id = oi.product_id
                WHERE p.user_id = ? AND o.created_at >= ?
                """,
                (user_id, current_month_start),
            )
            current_orders = int(cursor.fetchone()["total"] or 0)
            cursor.execute(
                """
                SELECT COUNT(DISTINCT o.id) AS total
                FROM Orders o
                JOIN OrderItems oi ON oi.order_id = o.id
                JOIN Products p ON p.id = oi.product_id
                WHERE p.user_id = ? AND o.created_at >= ? AND o.created_at < ?
                """,
                (user_id, previous_month_start, current_month_start),
            )
            previous_orders = int(cursor.fetchone()["total"] or 0)

            cursor.execute(
                """
                SELECT COUNT(DISTINCT o.user_id) AS total
                FROM Orders o
                JOIN OrderItems oi ON oi.order_id = o.id
                JOIN Products p ON p.id = oi.product_id
                WHERE p.user_id = ?
                """,
                (user_id,),
            )
            total_buyers = int(cursor.fetchone()["total"] or 0)
            cursor.execute(
                """
                SELECT COUNT(DISTINCT o.user_id) AS total
                FROM Orders o
                JOIN OrderItems oi ON oi.order_id = o.id
                JOIN Products p ON p.id = oi.product_id
                WHERE p.user_id = ? AND o.created_at >= ?
                """,
                (user_id, current_month_start),
            )
            current_buyers = int(cursor.fetchone()["total"] or 0)
            cursor.execute(
                """
                SELECT COUNT(DISTINCT o.user_id) AS total
                FROM Orders o
                JOIN OrderItems oi ON oi.order_id = o.id
                JOIN Products p ON p.id = oi.product_id
                WHERE p.user_id = ? AND o.created_at >= ? AND o.created_at < ?
                """,
                (user_id, previous_month_start, current_month_start),
            )
            previous_buyers = int(cursor.fetchone()["total"] or 0)

            cursor.execute(
                """
                SELECT COALESCE(SUM(oi.quantity * oi.unit_price), 0) AS total
                FROM Orders o
                JOIN OrderItems oi ON oi.order_id = o.id
                JOIN Products p ON p.id = oi.product_id
                WHERE p.user_id = ? AND LOWER(o.status) = 'completed'
                """,
                (user_id,),
            )
            total_revenue = float(cursor.fetchone()["total"] or 0)
            cursor.execute(
                """
                SELECT COALESCE(SUM(oi.quantity * oi.unit_price), 0) AS total
                FROM Orders o
                JOIN OrderItems oi ON oi.order_id = o.id
                JOIN Products p ON p.id = oi.product_id
                WHERE p.user_id = ? AND LOWER(o.status) = 'completed' AND o.created_at >= ?
                """,
                (user_id, current_month_start),
            )
            current_revenue = float(cursor.fetchone()["total"] or 0)
            cursor.execute(
                """
                SELECT COALESCE(SUM(oi.quantity * oi.unit_price), 0) AS total
                FROM Orders o
                JOIN OrderItems oi ON oi.order_id = o.id
                JOIN Products p ON p.id = oi.product_id
                WHERE p.user_id = ? AND LOWER(o.status) = 'completed' AND o.created_at >= ? AND o.created_at < ?
                """,
                (user_id, previous_month_start, current_month_start),
            )
            previous_revenue = float(cursor.fetchone()["total"] or 0)

            cursor.execute(
                """
                SELECT DISTINCT o.id, o.created_at
                FROM Orders o
                JOIN OrderItems oi ON oi.order_id = o.id
                JOIN Products p ON p.id = oi.product_id
                WHERE p.user_id = ? AND o.created_at >= ?
                ORDER BY o.created_at ASC, o.id ASC
                """,
                (user_id, oldest_month_start),
            )
            monthly_counts = {month["key"]: 0 for month in months}
            for row in cursor.fetchall():
                month_key = _month_key(row["created_at"])
                if month_key in monthly_counts:
                    monthly_counts[month_key] += 1

            cursor.execute(
                """
                SELECT COALESCE(NULLIF(TRIM(category), ''), 'Uncategorized') AS category_name, COUNT(*) AS total
                FROM Products
                WHERE user_id = ?
                  AND COALESCE(is_active, 1) = 1
                GROUP BY COALESCE(NULLIF(TRIM(category), ''), 'Uncategorized')
                ORDER BY total DESC, category_name ASC
                LIMIT 6
                """,
                (user_id,),
            )
            split_rows = cursor.fetchall()

            cursor.execute(
                """
                SELECT DISTINCT o.id
                FROM Orders o
                JOIN OrderItems oi ON oi.order_id = o.id
                JOIN Products p ON p.id = oi.product_id
                WHERE p.user_id = ?
                ORDER BY o.created_at DESC, o.id DESC
                LIMIT 5
                """,
                (user_id,),
            )
            recent_items = []
            for row in cursor.fetchall():
                summary = _build_farmer_order_summary(cursor, row["id"], user_id)
                if summary is None:
                    continue
                recent_items.append(
                    {
                        "id": summary["reference"],
                        "title": summary["counterparty_name"],
                        "subtitle": summary["counterparty_company"] or summary["counterparty_country"],
                        "detail": summary["product"],
                        "time": summary["date"],
                    }
                )

            payload = {
                "accountType": "farmer",
                "stats": [
                    {"id": "active_listings", "label": "Active Listings", "value": str(total_listings), "change": _format_signed_count(current_listings - previous_listings), "direction": _direction_for_change(current_listings - previous_listings), "helpText": "vs last month"},
                    {"id": "orders_received", "label": "Orders Received", "value": str(total_orders), "change": _format_signed_count(current_orders - previous_orders), "direction": _direction_for_change(current_orders - previous_orders), "helpText": "vs last month"},
                    {"id": "buyers", "label": "Buyers", "value": str(total_buyers), "change": _format_signed_count(current_buyers - previous_buyers), "direction": _direction_for_change(current_buyers - previous_buyers), "helpText": "vs last month"},
                    {"id": "revenue", "label": "Revenue", "value": _format_currency(total_revenue), "change": _format_signed_percent(_percent_change(current_revenue, previous_revenue)), "direction": _direction_for_change(_percent_change(current_revenue, previous_revenue)), "helpText": "vs last month"},
                ],
                "chart": {"label": "Orders by Month", "data": [{"month": month["label"], "value": monthly_counts[month["key"]]} for month in months]},
                "distribution": {"label": "Listing Categories", "data": [{"name": row["category_name"], "value": int(row["total"] or 0)} for row in split_rows]},
                "recent": {"label": "Recent Buyers", "items": recent_items},
            }
        else:
            cursor.execute("SELECT COUNT(*) AS total FROM Orders WHERE user_id = ?", (user_id,))
            total_orders = int(cursor.fetchone()["total"] or 0)
            cursor.execute("SELECT COUNT(*) AS total FROM Orders WHERE user_id = ? AND created_at >= ?", (user_id, current_month_start))
            current_orders = int(cursor.fetchone()["total"] or 0)
            cursor.execute("SELECT COUNT(*) AS total FROM Orders WHERE user_id = ? AND created_at >= ? AND created_at < ?", (user_id, previous_month_start, current_month_start))
            previous_orders = int(cursor.fetchone()["total"] or 0)

            cursor.execute("SELECT COALESCE(SUM(total_price), 0) AS total FROM Orders WHERE user_id = ?", (user_id,))
            total_spend = float(cursor.fetchone()["total"] or 0)
            cursor.execute("SELECT COALESCE(SUM(total_price), 0) AS total FROM Orders WHERE user_id = ? AND created_at >= ?", (user_id, current_month_start))
            current_spend = float(cursor.fetchone()["total"] or 0)
            cursor.execute("SELECT COALESCE(SUM(total_price), 0) AS total FROM Orders WHERE user_id = ? AND created_at >= ? AND created_at < ?", (user_id, previous_month_start, current_month_start))
            previous_spend = float(cursor.fetchone()["total"] or 0)

            cursor.execute(
                """
                SELECT COUNT(DISTINCT p.user_id) AS total
                FROM Orders o
                JOIN OrderItems oi ON oi.order_id = o.id
                JOIN Products p ON p.id = oi.product_id
                WHERE o.user_id = ?
                """,
                (user_id,),
            )
            total_suppliers = int(cursor.fetchone()["total"] or 0)
            cursor.execute(
                """
                SELECT COUNT(DISTINCT p.user_id) AS total
                FROM Orders o
                JOIN OrderItems oi ON oi.order_id = o.id
                JOIN Products p ON p.id = oi.product_id
                WHERE o.user_id = ? AND o.created_at >= ?
                """,
                (user_id, current_month_start),
            )
            current_suppliers = int(cursor.fetchone()["total"] or 0)
            cursor.execute(
                """
                SELECT COUNT(DISTINCT p.user_id) AS total
                FROM Orders o
                JOIN OrderItems oi ON oi.order_id = o.id
                JOIN Products p ON p.id = oi.product_id
                WHERE o.user_id = ? AND o.created_at >= ? AND o.created_at < ?
                """,
                (user_id, previous_month_start, current_month_start),
            )
            previous_suppliers = int(cursor.fetchone()["total"] or 0)

            cursor.execute(
                """
                SELECT COUNT(DISTINCT COALESCE(cp.country, '')) AS total
                FROM Orders o
                JOIN OrderItems oi ON oi.order_id = o.id
                JOIN Products p ON p.id = oi.product_id
                LEFT JOIN ConnectProfiles cp ON cp.user_id = p.user_id
                WHERE o.user_id = ? AND TRIM(COALESCE(cp.country, '')) != ''
                """,
                (user_id,),
            )
            total_markets = int(cursor.fetchone()["total"] or 0)
            cursor.execute(
                """
                SELECT COUNT(DISTINCT COALESCE(cp.country, '')) AS total
                FROM Orders o
                JOIN OrderItems oi ON oi.order_id = o.id
                JOIN Products p ON p.id = oi.product_id
                LEFT JOIN ConnectProfiles cp ON cp.user_id = p.user_id
                WHERE o.user_id = ? AND TRIM(COALESCE(cp.country, '')) != '' AND o.created_at >= ?
                """,
                (user_id, current_month_start),
            )
            current_markets = int(cursor.fetchone()["total"] or 0)
            cursor.execute(
                """
                SELECT COUNT(DISTINCT COALESCE(cp.country, '')) AS total
                FROM Orders o
                JOIN OrderItems oi ON oi.order_id = o.id
                JOIN Products p ON p.id = oi.product_id
                LEFT JOIN ConnectProfiles cp ON cp.user_id = p.user_id
                WHERE o.user_id = ? AND TRIM(COALESCE(cp.country, '')) != '' AND o.created_at >= ? AND o.created_at < ?
                """,
                (user_id, previous_month_start, current_month_start),
            )
            previous_markets = int(cursor.fetchone()["total"] or 0)

            cursor.execute("SELECT id, created_at FROM Orders WHERE user_id = ? AND created_at >= ? ORDER BY created_at ASC, id ASC", (user_id, oldest_month_start))
            monthly_counts = {month["key"]: 0 for month in months}
            for row in cursor.fetchall():
                month_key = _month_key(row["created_at"])
                if month_key in monthly_counts:
                    monthly_counts[month_key] += 1

            cursor.execute(
                """
                SELECT COALESCE(NULLIF(TRIM(p.category), ''), 'Uncategorized') AS category_name, COUNT(*) AS total
                FROM Orders o
                JOIN OrderItems oi ON oi.order_id = o.id
                LEFT JOIN Products p ON p.id = oi.product_id
                WHERE o.user_id = ?
                GROUP BY COALESCE(NULLIF(TRIM(p.category), ''), 'Uncategorized')
                ORDER BY total DESC, category_name ASC
                LIMIT 6
                """,
                (user_id,),
            )
            split_rows = cursor.fetchall()

            cursor.execute("SELECT id FROM Orders WHERE user_id = ? ORDER BY created_at DESC, id DESC LIMIT 5", (user_id,))
            recent_items = []
            for row in cursor.fetchall():
                summary = _build_importer_order_summary(cursor, row["id"])
                if summary is None:
                    continue
                recent_items.append(
                    {
                        "id": summary["reference"],
                        "title": summary["counterparty_name"],
                        "subtitle": summary["counterparty_company"] or summary["counterparty_country"],
                        "detail": summary["product"],
                        "time": summary["date"],
                    }
                )

            payload = {
                "accountType": "importer",
                "stats": [
                    {"id": "orders_placed", "label": "Orders Placed", "value": str(total_orders), "change": _format_signed_count(current_orders - previous_orders), "direction": _direction_for_change(current_orders - previous_orders), "helpText": "vs last month"},
                    {"id": "total_spend", "label": "Total Spend", "value": _format_currency(total_spend), "change": _format_signed_percent(_percent_change(current_spend, previous_spend)), "direction": _direction_for_change(_percent_change(current_spend, previous_spend)), "helpText": "vs last month"},
                    {"id": "suppliers", "label": "Suppliers", "value": str(total_suppliers), "change": _format_signed_count(current_suppliers - previous_suppliers), "direction": _direction_for_change(current_suppliers - previous_suppliers), "helpText": "vs last month"},
                    {"id": "markets", "label": "Markets", "value": str(total_markets), "change": _format_signed_count(current_markets - previous_markets), "direction": _direction_for_change(current_markets - previous_markets), "helpText": "vs last month"},
                ],
                "chart": {"label": "Orders by Month", "data": [{"month": month["label"], "value": monthly_counts[month["key"]]} for month in months]},
                "distribution": {"label": "Ordered Categories", "data": [{"name": row["category_name"], "value": int(row["total"] or 0)} for row in split_rows]},
                "recent": {"label": "Recent Orders", "items": recent_items},
            }

        conn.close()
        return jsonify(envelope(payload, "Dashboard overview fetched", 200)), 200
    except Exception as e:
        logger.exception("Failed to fetch connect dashboard overview for %s", user_id)
        return jsonify(envelope(None, f"Error: {e}", 500, False)), 500
