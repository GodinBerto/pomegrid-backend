import logging

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

from database import db_connection
from decorators.roles import admin_required, get_authenticated_user_id, normalize_role
from routes.api_envelope import build_meta, envelope, parse_pagination


users = Blueprint("users", __name__)
logger = logging.getLogger(__name__)


def _serialize_user_row(row):
    user = dict(row)
    normalized_role = normalize_role(user.get("role") or user.get("user_type"), user.get("is_admin"))
    user["role"] = normalized_role
    user["status"] = str(user.get("status") or ("active" if bool(user.get("is_active")) else "inactive")).lower()
    user["is_admin"] = int(bool(user.get("is_admin")) or normalized_role == "admin")
    user["is_active"] = bool(user.get("is_active"))
    user["is_verified"] = bool(user.get("is_verified"))
    return user


@users.route("/me", methods=["GET"])
@jwt_required()
def get_current_user():
    user_id = get_authenticated_user_id()
    if user_id is None:
        return jsonify(envelope(None, "Invalid token identity", 401, False)), 401
    try:
        conn, cursor = db_connection()
        cursor.execute(
            """
            SELECT
                id,
                username,
                email,
                full_name,
                phone,
                user_type,
                role,
                status,
                is_admin,
                is_active,
                is_verified,
                address,
                profile_image_url,
                avatar,
                date_of_birth,
                created_at,
                updated_at
            FROM Users
            WHERE id = ?
            """,
            (user_id,),
        )
        row = cursor.fetchone()
        conn.close()
        if not row:
            return jsonify(envelope(None, "User not found", 404, False)), 404
        return jsonify(envelope(_serialize_user_row(row), "User fetched", 200)), 200
    except Exception as e:
        logger.exception("Failed to fetch current user")
        return jsonify(envelope(None, f"Error: {e}", 500, False)), 500


@users.route("/me", methods=["PUT"])
@jwt_required()
def update_current_user():
    user_id = get_authenticated_user_id()
    if user_id is None:
        return jsonify(envelope(None, "Invalid token identity", 401, False)), 401
    data = request.get_json() or {}
    allowed_fields = ["full_name", "phone", "address", "profile_image_url", "date_of_birth", "avatar"]
    updates = {k: data[k] for k in allowed_fields if k in data}
    if not updates:
        return jsonify(envelope(None, "No profile fields provided", 400, False)), 400

    if "avatar" in updates:
        updates["profile_image_url"] = updates["avatar"]

    set_clause = ", ".join([f"{k} = ?" for k in updates.keys()])
    values = list(updates.values()) + [user_id]

    try:
        conn, cursor = db_connection()
        cursor.execute(
            f"UPDATE Users SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            tuple(values),
        )
        conn.commit()
        cursor.execute(
            """
            SELECT
                id,
                username,
                email,
                full_name,
                phone,
                user_type,
                role,
                status,
                is_admin,
                is_active,
                is_verified,
                address,
                profile_image_url,
                avatar,
                date_of_birth,
                created_at,
                updated_at
            FROM Users
            WHERE id = ?
            """,
            (user_id,),
        )
        row = cursor.fetchone()
        conn.close()
        if not row:
            return jsonify(envelope(None, "User not found", 404, False)), 404
        return jsonify(envelope(_serialize_user_row(row), "Profile updated", 200)), 200
    except Exception as e:
        logger.exception("Failed to update current user")
        return jsonify(envelope(None, f"Error: {e}", 500, False)), 500


@users.route("", methods=["GET"])
@users.route("/", methods=["GET"])
@admin_required
def admin_list_users():
    page, per_page, offset = parse_pagination(request.args)
    search = str(request.args.get("search") or "").strip()
    status = str(request.args.get("status") or "").strip().lower()
    if status and status not in {"active", "inactive"}:
        return jsonify(envelope(None, "status must be active|inactive", 400, False)), 400

    where = ["1=1"]
    params = []
    if search:
        like = f"%{search}%"
        where.append("(LOWER(COALESCE(full_name, '')) LIKE LOWER(?) OR LOWER(COALESCE(email, '')) LIKE LOWER(?))")
        params.extend([like, like])
    if status:
        where.append("LOWER(COALESCE(status, CASE WHEN is_active = 1 THEN 'active' ELSE 'inactive' END)) = ?")
        params.append(status)
    where_sql = " AND ".join(where)

    try:
        conn, cursor = db_connection()
        cursor.execute(f"SELECT COUNT(*) AS total FROM Users WHERE {where_sql}", tuple(params))
        total = int(cursor.fetchone()["total"] or 0)

        query_params = list(params) + [per_page, offset]
        cursor.execute(
            f"""
            SELECT
                id,
                full_name,
                email,
                role,
                user_type,
                status,
                is_active,
                is_admin,
                created_at,
                updated_at
            FROM Users
            WHERE {where_sql}
            ORDER BY created_at DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            tuple(query_params),
        )
        rows = cursor.fetchall()
        conn.close()

        payload = [_serialize_user_row(row) for row in rows]
        meta = build_meta(page, per_page, total)
        return jsonify(envelope(payload, "Users fetched", 200, True, meta)), 200
    except Exception as e:
        logger.exception("Failed to list users")
        return jsonify(envelope(None, f"Error: {e}", 500, False)), 500


@users.route("/<int:user_id>", methods=["GET"])
@admin_required
def admin_get_user(user_id):
    try:
        conn, cursor = db_connection()
        cursor.execute(
            """
            SELECT
                id,
                username,
                full_name,
                email,
                phone,
                role,
                user_type,
                status,
                is_active,
                is_admin,
                is_verified,
                address,
                profile_image_url,
                avatar,
                date_of_birth,
                created_at,
                updated_at
            FROM Users
            WHERE id = ?
            """,
            (user_id,),
        )
        row = cursor.fetchone()
        conn.close()
        if not row:
            return jsonify(envelope(None, "User not found", 404, False)), 404
        return jsonify(envelope(_serialize_user_row(row), "User fetched", 200)), 200
    except Exception as e:
        logger.exception("Failed to fetch user %s", user_id)
        return jsonify(envelope(None, f"Error: {e}", 500, False)), 500


@users.route("/<int:user_id>/orders", methods=["GET"])
@admin_required
def admin_get_user_orders(user_id):
    page, per_page, offset = parse_pagination(request.args)
    try:
        conn, cursor = db_connection()
        cursor.execute("SELECT id, full_name, email FROM Users WHERE id = ?", (user_id,))
        user_row = cursor.fetchone()
        if not user_row:
            conn.close()
            return jsonify(envelope(None, "User not found", 404, False)), 404

        cursor.execute("SELECT COUNT(*) AS total FROM Orders WHERE user_id = ?", (user_id,))
        total = int(cursor.fetchone()["total"] or 0)

        cursor.execute(
            """
            SELECT
                id,
                user_id,
                status,
                total_price,
                payment_method,
                shipping_address,
                notes,
                created_at,
                updated_at
            FROM Orders
            WHERE user_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            (user_id, per_page, offset),
        )
        order_rows = cursor.fetchall()
        order_payload = []
        for order_row in order_rows:
            order_data = dict(order_row)
            order_data["total_price"] = float(order_data.get("total_price") or 0)
            cursor.execute(
                """
                SELECT id, order_id, product_id, name, quantity, unit_price, created_at
                FROM OrderItems
                WHERE order_id = ?
                ORDER BY id ASC
                """,
                (order_data["id"],),
            )
            items = [dict(item) for item in cursor.fetchall()]
            order_data["items"] = items
            order_payload.append(order_data)

        conn.close()
        meta = build_meta(page, per_page, total)
        payload = {
            "user": {
                "id": int(user_row["id"]),
                "full_name": user_row["full_name"],
                "email": user_row["email"],
            },
            "orders": order_payload,
        }
        return jsonify(envelope(payload, "User orders fetched", 200, True, meta)), 200
    except Exception as e:
        logger.exception("Failed to fetch orders for user %s", user_id)
        return jsonify(envelope(None, f"Error: {e}", 500, False)), 500
