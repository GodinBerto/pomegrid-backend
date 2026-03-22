from flask import jsonify, request

from database import db_connection
from routes.api_envelope import build_meta, envelope, parse_pagination

from .common import (
    _current_user_id,
    _format_currency,
    _format_date,
    _normalize_account_type,
    _safe_text,
    connect_api,
    logger,
)
from .profiles import _require_connect_profile


def _seller_order_items(cursor, order_id, seller_id):
    cursor.execute(
        """
        SELECT
            oi.id,
            oi.product_id,
            oi.name,
            oi.quantity,
            oi.unit_price
        FROM OrderItems oi
        JOIN Products p ON p.id = oi.product_id
        WHERE oi.order_id = ? AND p.user_id = ?
        ORDER BY oi.id ASC
        """,
        (int(order_id), int(seller_id)),
    )
    items = []
    for row in cursor.fetchall():
        quantity = int(row["quantity"] or 0)
        unit_price = float(row["unit_price"] or 0)
        items.append(
            {
                "id": int(row["id"]),
                "product_id": int(row["product_id"]) if row["product_id"] is not None else None,
                "name": row["name"],
                "quantity": quantity,
                "unit_price": unit_price,
                "line_total": round(quantity * unit_price, 2),
            }
        )
    return items


def _buyer_order_items(cursor, order_id):
    cursor.execute(
        """
        SELECT
            oi.id,
            oi.product_id,
            oi.name,
            oi.quantity,
            oi.unit_price,
            p.user_id AS supplier_id,
            u.full_name AS supplier_name,
            cp.company AS supplier_company,
            cp.country AS supplier_country
        FROM OrderItems oi
        LEFT JOIN Products p ON p.id = oi.product_id
        LEFT JOIN Users u ON u.id = p.user_id
        LEFT JOIN ConnectProfiles cp ON cp.user_id = p.user_id
        WHERE oi.order_id = ?
        ORDER BY oi.id ASC
        """,
        (int(order_id),),
    )
    items = []
    for row in cursor.fetchall():
        quantity = int(row["quantity"] or 0)
        unit_price = float(row["unit_price"] or 0)
        items.append(
            {
                "id": int(row["id"]),
                "product_id": int(row["product_id"]) if row["product_id"] is not None else None,
                "name": row["name"],
                "quantity": quantity,
                "unit_price": unit_price,
                "line_total": round(quantity * unit_price, 2),
                "supplier_id": int(row["supplier_id"]) if row["supplier_id"] is not None else None,
                "supplier_name": row["supplier_name"],
                "supplier_company": _safe_text(row["supplier_company"]),
                "supplier_country": _safe_text(row["supplier_country"]),
            }
        )
    return items


def _summarize_product_names(items):
    names = []
    seen = set()
    for item in items:
        name = _safe_text(item.get("name"))
        if name and name not in seen:
            seen.add(name)
            names.append(name)

    if not names:
        return "No products"
    if len(names) == 1:
        return names[0]
    return f"{names[0]} +{len(names) - 1}"


def _format_total_quantity(items):
    total_quantity = sum(int(item.get("quantity") or 0) for item in items)
    return f"{total_quantity:,} units"


def _build_farmer_order_summary(cursor, order_id, seller_id):
    cursor.execute(
        """
        SELECT
            o.id,
            o.user_id,
            o.status,
            o.created_at,
            u.full_name AS buyer_name,
            cp.company AS buyer_company,
            cp.country AS buyer_country
        FROM Orders o
        LEFT JOIN Users u ON u.id = o.user_id
        LEFT JOIN ConnectProfiles cp ON cp.user_id = o.user_id
        WHERE o.id = ?
        LIMIT 1
        """,
        (int(order_id),),
    )
    order_row = cursor.fetchone()
    if not order_row:
        return None

    items = _seller_order_items(cursor, order_id, seller_id)
    relevant_total = round(sum(item["line_total"] for item in items), 2)
    return {
        "id": int(order_row["id"]),
        "reference": f"ORD-{int(order_row['id']):04d}",
        "scope": "seller",
        "product": _summarize_product_names(items),
        "counterparty_name": order_row["buyer_name"] or "Buyer",
        "counterparty_company": _safe_text(order_row["buyer_company"]),
        "counterparty_country": _safe_text(order_row["buyer_country"]),
        "quantity": _format_total_quantity(items),
        "price": _format_currency(relevant_total),
        "total_value": relevant_total,
        "status": _safe_text(order_row["status"]).lower() or "pending",
        "date": _format_date(order_row["created_at"]),
        "created_at": order_row["created_at"],
        "items": items,
    }


def _build_importer_order_summary(cursor, order_id):
    cursor.execute(
        """
        SELECT id, status, total_price, created_at
        FROM Orders
        WHERE id = ?
        LIMIT 1
        """,
        (int(order_id),),
    )
    order_row = cursor.fetchone()
    if not order_row:
        return None

    items = _buyer_order_items(cursor, order_id)
    suppliers = {}
    for item in items:
        supplier_id = item.get("supplier_id")
        if supplier_id is None or supplier_id in suppliers:
            continue
        suppliers[supplier_id] = {
            "name": item.get("supplier_name") or "Supplier",
            "company": item.get("supplier_company"),
            "country": item.get("supplier_country"),
        }

    supplier_values = list(suppliers.values())
    if len(supplier_values) == 1:
        counterparty_name = supplier_values[0]["name"]
        counterparty_company = supplier_values[0]["company"]
        counterparty_country = supplier_values[0]["country"]
    elif len(supplier_values) > 1:
        counterparty_name = f"{len(supplier_values)} suppliers"
        counterparty_company = "Multiple sellers"
        countries = [item["country"] for item in supplier_values if _safe_text(item["country"])]
        counterparty_country = countries[0] if len(set(countries)) == 1 and countries else "Multiple countries"
    else:
        counterparty_name = "Supplier"
        counterparty_company = ""
        counterparty_country = ""

    total_price = float(order_row["total_price"] or 0)
    return {
        "id": int(order_row["id"]),
        "reference": f"ORD-{int(order_row['id']):04d}",
        "scope": "buyer",
        "product": _summarize_product_names(items),
        "counterparty_name": counterparty_name,
        "counterparty_company": counterparty_company,
        "counterparty_country": counterparty_country,
        "quantity": _format_total_quantity(items),
        "price": _format_currency(total_price),
        "total_value": total_price,
        "status": _safe_text(order_row["status"]).lower() or "pending",
        "date": _format_date(order_row["created_at"]),
        "created_at": order_row["created_at"],
        "items": items,
    }


@connect_api.route("/orders", methods=["GET"])
def list_connect_orders():
    user_id = _current_user_id()
    page, per_page, offset = parse_pagination(request.args)
    scope = _safe_text(request.args.get("scope")).lower()

    try:
        conn, cursor = db_connection()
        profile_row = _require_connect_profile(cursor, user_id)
        if not profile_row:
            conn.close()
            return jsonify(envelope(None, "Connect profile not found", 404, False)), 404

        account_type = _normalize_account_type(profile_row["account_type"])
        if scope not in {"buyer", "seller"}:
            scope = "seller" if account_type == "farmer" else "buyer"

        if scope == "seller":
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
            total = int(cursor.fetchone()["total"] or 0)
            cursor.execute(
                """
                SELECT DISTINCT o.id
                FROM Orders o
                JOIN OrderItems oi ON oi.order_id = o.id
                JOIN Products p ON p.id = oi.product_id
                WHERE p.user_id = ?
                ORDER BY o.created_at DESC, o.id DESC
                LIMIT ? OFFSET ?
                """,
                (user_id, per_page, offset),
            )
            order_ids = [int(row["id"]) for row in cursor.fetchall()]
            items = [
                summary
                for summary in (_build_farmer_order_summary(cursor, order_id, user_id) for order_id in order_ids)
                if summary is not None
            ]
        else:
            cursor.execute("SELECT COUNT(*) AS total FROM Orders WHERE user_id = ?", (user_id,))
            total = int(cursor.fetchone()["total"] or 0)
            cursor.execute(
                """
                SELECT id
                FROM Orders
                WHERE user_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                (user_id, per_page, offset),
            )
            order_ids = [int(row["id"]) for row in cursor.fetchall()]
            items = [
                summary
                for summary in (_build_importer_order_summary(cursor, order_id) for order_id in order_ids)
                if summary is not None
            ]

        conn.close()

        meta = build_meta(page, per_page, total)
        return jsonify(envelope(items, "Orders fetched", 200, True, meta)), 200
    except Exception as e:
        logger.exception("Failed to list connect orders for %s", user_id)
        return jsonify(envelope(None, f"Error: {e}", 500, False)), 500
