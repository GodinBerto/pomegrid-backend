from flask import jsonify, request
from flask_jwt_extended import jwt_required

from database.connection import db_connection
from middleware.authMiddleware import get_authenticated_user_id
from routes.api_envelope import envelope
from . import food_trade_api
from .utils import check_admin


@food_trade_api.route("/categories", methods=["GET"])
def list_categories():
    conn, cursor = db_connection()
    cursor.execute("SELECT id, name, slug, sort_order, image_url FROM food_trade_categories WHERE is_active = 1 ORDER BY sort_order ASC")
    rows = cursor.fetchall()
    conn.close()
    
    categories = [dict(row) for row in rows]
    return jsonify(envelope(categories, "Categories retrieved successfully", 200, True)), 200


@food_trade_api.route("/admin/categories", methods=["GET"])
@jwt_required()
def admin_list_categories():
    user_id = get_authenticated_user_id()
    if not check_admin(user_id):
        return jsonify(envelope(None, "Forbidden: admin only", 403, False)), 403
        
    conn, cursor = db_connection()
    cursor.execute("SELECT id, name, slug, sort_order, image_url FROM food_trade_categories ORDER BY sort_order ASC")
    rows = cursor.fetchall()
    conn.close()
    return jsonify(envelope([dict(r) for r in rows], "Admin categories", 200, True)), 200


@food_trade_api.route("/admin/categories/<int:category_id>", methods=["GET"])
@jwt_required()
def admin_get_category(category_id):
    user_id = get_authenticated_user_id()
    if not check_admin(user_id):
        return jsonify(envelope(None, "Forbidden: admin only", 403, False)), 403

    conn, cursor = db_connection()
    cursor.execute(
        """
        SELECT id, name, slug, sort_order, image_url, is_active
        FROM food_trade_categories
        WHERE id = ?
        """,
        (category_id,),
    )
    row = cursor.fetchone()
    conn.close()

    if not row:
        return jsonify(envelope(None, "Category not found", 404, False)), 404

    return jsonify(envelope(dict(row), "Category retrieved successfully", 200, True)), 200


@food_trade_api.route("/admin/categories", methods=["POST"])
@jwt_required()
def admin_create_category():
    user_id = get_authenticated_user_id()
    if not check_admin(user_id):
        return jsonify(envelope(None, "Forbidden: admin only", 403, False)), 403

    data = request.get_json()

    name = data.get("name")
    slug = data.get("slug")
    sort_order = data.get("sort_order", 0)
    image_url = str(data.get("image_url") or "").strip() or None
    is_active = data.get("is_active", 1)

    if not name or not slug:
        return jsonify(envelope(None, "Name and slug are required", 400, False)), 400

    conn, cursor = db_connection()

    cursor.execute(
        "SELECT id FROM food_trade_categories WHERE slug = ?",
        (slug,),
    )

    if cursor.fetchone():
        conn.close()
        return jsonify(envelope(None, "Slug already exists", 400, False)), 400

    cursor.execute(
        """
        INSERT INTO food_trade_categories
        (name, slug, sort_order, image_url, is_active)
        VALUES (?, ?, ?, ?, ?)
        """,
        (name, slug, sort_order, image_url, is_active),
    )

    conn.commit()
    category_id = cursor.lastrowid
    conn.close()

    return (
        jsonify(
            envelope(
                {"id": category_id},
                "Category created successfully",
                201,
                True,
            )
        ),
        201,
    )


@food_trade_api.route("/admin/categories/<int:category_id>", methods=["PUT"])
@jwt_required()
def admin_update_category(category_id):
    user_id = get_authenticated_user_id()
    if not check_admin(user_id):
        return jsonify(envelope(None, "Forbidden: admin only", 403, False)), 403

    data = request.get_json()

    name = data.get("name")
    slug = data.get("slug")
    sort_order = data.get("sort_order")
    image_url = data.get("image_url")
    if image_url is not None:
        image_url = str(image_url).strip() or None
    is_active = data.get("is_active")

    conn, cursor = db_connection()

    cursor.execute(
        "SELECT id FROM food_trade_categories WHERE id = ?",
        (category_id,),
    )

    if not cursor.fetchone():
        conn.close()
        return jsonify(envelope(None, "Category not found", 404, False)), 404

    if slug:
        cursor.execute(
            """
            SELECT id
            FROM food_trade_categories
            WHERE slug = ? AND id != ?
            """,
            (slug, category_id),
        )

        if cursor.fetchone():
            conn.close()
            return jsonify(envelope(None, "Slug already exists", 400, False)), 400

    cursor.execute(
        """
        UPDATE food_trade_categories
        SET
            name = COALESCE(?, name),
            slug = COALESCE(?, slug),
            sort_order = COALESCE(?, sort_order),
            image_url = COALESCE(?, image_url),
            is_active = COALESCE(?, is_active)
        WHERE id = ?
        """,
        (
            name,
            slug,
            sort_order,
            image_url,
            is_active,
            category_id,
        ),
    )

    conn.commit()
    conn.close()

    return jsonify(envelope(None, "Category updated successfully", 200, True)), 200


@food_trade_api.route("/admin/categories/<int:category_id>", methods=["DELETE"])
@jwt_required()
def admin_delete_category(category_id):
    user_id = get_authenticated_user_id()
    if not check_admin(user_id):
        return jsonify(envelope(None, "Forbidden: admin only", 403, False)), 403

    conn, cursor = db_connection()

    cursor.execute(
        "SELECT id FROM food_trade_categories WHERE id = ?",
        (category_id,),
    )

    if not cursor.fetchone():
        conn.close()
        return jsonify(envelope(None, "Category not found", 404, False)), 404

    cursor.execute(
        "DELETE FROM food_trade_categories WHERE id = ?",
        (category_id,),
    )

    conn.commit()
    conn.close()

    return jsonify(envelope(None, "Category deleted successfully", 200, True)), 200
