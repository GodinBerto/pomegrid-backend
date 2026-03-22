from flask import jsonify, request

from database import db_connection
from routes.api_envelope import build_meta, envelope, parse_pagination

from .common import _normalize_account_type, _safe_text, connect_api, logger
from .profiles import _fetch_connect_profile_row, _serialize_connect_profile


def _product_name_list(cursor, user_id):
    cursor.execute(
        """
        SELECT title
        FROM Products
        WHERE user_id = ?
        ORDER BY created_at DESC, id DESC
        LIMIT 8
        """,
        (int(user_id),),
    )
    return [_safe_text(row["title"]) for row in cursor.fetchall() if _safe_text(row["title"])]


def _importer_interest_list(cursor, user_id):
    cursor.execute(
        """
        SELECT DISTINCT oi.name
        FROM Orders o
        JOIN OrderItems oi ON oi.order_id = o.id
        WHERE o.user_id = ?
        ORDER BY oi.name ASC
        LIMIT 8
        """,
        (int(user_id),),
    )
    return [_safe_text(row["name"]) for row in cursor.fetchall() if _safe_text(row["name"])]


def _partner_total_deals(cursor, user_id, account_type):
    if account_type == "farmer":
        cursor.execute(
            """
            SELECT COUNT(DISTINCT o.id) AS total
            FROM Orders o
            JOIN OrderItems oi ON oi.order_id = o.id
            JOIN Products p ON p.id = oi.product_id
            WHERE p.user_id = ?
            """,
            (int(user_id),),
        )
    else:
        cursor.execute("SELECT COUNT(*) AS total FROM Orders WHERE user_id = ?", (int(user_id),))
    row = cursor.fetchone()
    return int(row["total"] or 0) if row else 0


def _partner_average_rating(cursor, user_id, account_type):
    if account_type != "farmer":
        return 0.0
    cursor.execute(
        """
        SELECT AVG(COALESCE(rating, 0)) AS average_rating
        FROM Products
        WHERE user_id = ?
        """,
        (int(user_id),),
    )
    row = cursor.fetchone()
    return round(float(row["average_rating"] or 0), 1) if row else 0.0


def _build_partner_payload(cursor, user_id):
    row = _fetch_connect_profile_row(cursor, user_id)
    if not row:
        return None

    profile = _serialize_connect_profile(row)
    account_type = profile["account_type"]
    if account_type is None:
        return None

    products = _product_name_list(cursor, user_id)
    if account_type == "importer":
        products = _importer_interest_list(cursor, user_id) or products

    return {
        "id": int(profile["id"]),
        "name": profile["name"],
        "company": profile["company"] or profile["name"],
        "type": account_type,
        "country": profile["country"],
        "products": products,
        "verified": bool(profile["is_verified"]),
        "avatar": profile["avatar"],
        "bio": profile["bio"],
        "phone": profile["phone"],
        "email": profile["email"],
        "established": profile["established"],
        "certifications": [],
        "minOrderQty": profile["min_order_qty"],
        "shippingMethods": [],
        "languages": [],
        "rating": _partner_average_rating(cursor, user_id, account_type),
        "totalDeals": _partner_total_deals(cursor, user_id, account_type),
        "responseTime": profile["response_time"],
    }


@connect_api.route("/partners", methods=["GET"])
def list_connect_partners():
    page, per_page, offset = parse_pagination(request.args)
    search = _safe_text(request.args.get("search")).lower()
    partner_type = _normalize_account_type(request.args.get("type"))

    where = ["cp.account_type IS NOT NULL", "COALESCE(u.is_active, 1) = 1"]
    params = []

    if partner_type:
        where.append("cp.account_type = ?")
        params.append(partner_type)

    if search:
        like = f"%{search}%"
        where.append(
            """
            (
                LOWER(COALESCE(u.full_name, '')) LIKE LOWER(?)
                OR LOWER(COALESCE(cp.company, '')) LIKE LOWER(?)
                OR LOWER(COALESCE(cp.country, '')) LIKE LOWER(?)
                OR LOWER(COALESCE(cp.bio, '')) LIKE LOWER(?)
            )
            """
        )
        params.extend([like, like, like, like])

    where_sql = " AND ".join(where)

    try:
        conn, cursor = db_connection()
        cursor.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM ConnectProfiles cp
            JOIN Users u ON u.id = cp.user_id
            WHERE {where_sql}
            """,
            tuple(params),
        )
        total = int(cursor.fetchone()["total"] or 0)

        query_params = list(params) + [per_page, offset]
        cursor.execute(
            f"""
            SELECT u.id
            FROM ConnectProfiles cp
            JOIN Users u ON u.id = cp.user_id
            WHERE {where_sql}
            ORDER BY cp.updated_at DESC, u.full_name ASC, u.id DESC
            LIMIT ? OFFSET ?
            """,
            tuple(query_params),
        )
        partner_ids = [int(row["id"]) for row in cursor.fetchall()]
        items = []
        for partner_id in partner_ids:
            payload = _build_partner_payload(cursor, partner_id)
            if payload is not None:
                items.append(payload)
        conn.close()

        meta = build_meta(page, per_page, total)
        return jsonify(envelope(items, "Partners fetched", 200, True, meta)), 200
    except Exception as e:
        logger.exception("Failed to list connect partners")
        return jsonify(envelope(None, f"Error: {e}", 500, False)), 500
