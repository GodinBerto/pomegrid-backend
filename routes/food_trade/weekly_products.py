import re

from flask import jsonify, request
from flask_jwt_extended import jwt_required

from database import db_connection
from middleware.authMiddleware import get_authenticated_user_id
from routes.api_envelope import envelope
from . import food_trade_api
from .utils import check_admin


def normalize_slug(slug, name):
    raw_slug = (slug or "").strip() if slug is not None else ""
    if raw_slug:
        slug_value = raw_slug
    else:
        slug_value = (name or "").strip()

    if not slug_value:
        return None

    return re.sub(r"[^a-z0-9]+", "-", slug_value.lower()).strip("-")


def build_weekly_product_payload(row):
    if not row:
        return None

    product = dict(row)
    product["slug"] = normalize_slug(product.get("slug"), product.get("name")) or product.get("slug")

    if product.get("category_id") is not None:
        product["categories"] = {
            "id": product.get("category_id"),
            "name": product.get("category_name"),
        }
    elif product.get("category_name"):
        product["categories"] = {"id": None, "name": product.get("category_name")}

    return product


@food_trade_api.route("/weekly_products", methods=["GET"])
def get_weekly_products():
    conn, cursor = db_connection()
    try:
        cursor.execute(
            """
            SELECT wp.id, wp.name, wp.slug, wp.description, wp.price, wp.image_url,
                   wp.status, wp.category_id, c.name AS category_name,
                   wp.created_at, wp.updated_at
            FROM food_trade_weekly_products wp
            LEFT JOIN food_trade_categories c ON wp.category_id = c.id
            WHERE wp.status = 'active'
            ORDER BY wp.created_at DESC
            """
        )
        rows = cursor.fetchall()
        products = [build_weekly_product_payload(row) for row in rows]
        return jsonify(envelope(products, "Weekly products retrieved successfully.", 200)), 200
    except Exception:
        return jsonify(envelope(None, "Internal server error", 500, False)), 500
    finally:
        conn.close()


@food_trade_api.route("/weekly_products/<int:product_id>", methods=["GET"])
def get_weekly_product_by_id(product_id):
    conn, cursor = db_connection()
    try:
        cursor.execute(
            """
            SELECT wp.id, wp.name, wp.slug, wp.description, wp.price, wp.image_url,
                   wp.status, wp.category_id, c.name AS category_name,
                   wp.created_at, wp.updated_at
            FROM food_trade_weekly_products wp
            LEFT JOIN food_trade_categories c ON wp.category_id = c.id
            WHERE wp.id = ?
            """,
            (product_id,),
        )
        row = cursor.fetchone()
        if not row:
            return jsonify(envelope(None, "Product not found", 404, False)), 404

        return jsonify(envelope(build_weekly_product_payload(row), "Product retrieved successfully.", 200)), 200
    except Exception:
        return jsonify(envelope(None, "Internal server error", 500, False)), 500
    finally:
        conn.close()


@food_trade_api.route("/weekly_products", methods=["POST"])
@jwt_required()
def create_weekly_product():
    user_id = get_authenticated_user_id()
    if not check_admin(user_id):
        return jsonify(envelope(None, "Unauthorized", 403, False)), 403

    data = request.get_json() or {}
    name = str(data.get("name") or "").strip()
    description = str(data.get("description") or "").strip()
    price = data.get("price")
    image_url = str(data.get("image_url") or "").strip()
    status = str(data.get("status") or "inactive").strip().lower()
    slug = normalize_slug(data.get("slug"), name)
    category_id = data.get("category_id")

    if not name or price is None:
        return jsonify(envelope(None, "name and price are required", 400, False)), 400

    if status not in ("active", "inactive"):
        status = "inactive"

    conn, cursor = db_connection()
    try:
        cursor.execute(
            """
            INSERT INTO food_trade_weekly_products (
                name, slug, description, price, image_url, category_id, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (name, slug, description, float(price), image_url, category_id, status),
        )
        product_id = cursor.lastrowid
        conn.commit()
        return jsonify(envelope({"id": product_id}, "Product created successfully.", 201)), 201
    except Exception:
        conn.rollback()
        return jsonify(envelope(None, "Internal server error", 500, False)), 500
    finally:
        conn.close()


@food_trade_api.route("/weekly_products/<int:product_id>", methods=["PUT"])
@jwt_required()
def update_weekly_product(product_id):
    user_id = get_authenticated_user_id()
    if not check_admin(user_id):
        return jsonify(envelope(None, "Unauthorized", 403, False)), 403

    data = request.get_json() or {}
    name = str(data.get("name") or "").strip()
    description = str(data.get("description") or "").strip()
    price = data.get("price")
    image_url = str(data.get("image_url") or "").strip()
    status = str(data.get("status") or "").strip().lower()
    slug = data.get("slug")
    category_id = data.get("category_id")

    conn, cursor = db_connection()
    try:
        cursor.execute("SELECT id FROM food_trade_weekly_products WHERE id = ?", (product_id,))
        if not cursor.fetchone():
            return jsonify(envelope(None, "Product not found", 404, False)), 404

        update_fields = []
        params = []
        if name:
            update_fields.append("name = ?")
            params.append(name)
        if slug is not None:
            update_fields.append("slug = ?")
            params.append(normalize_slug(slug, name or None))
        if description:
            update_fields.append("description = ?")
            params.append(description)
        if price is not None:
            update_fields.append("price = ?")
            params.append(float(price))
        if image_url:
            update_fields.append("image_url = ?")
            params.append(image_url)
        if category_id is not None:
            update_fields.append("category_id = ?")
            params.append(category_id)
        if status in ("active", "inactive"):
            update_fields.append("status = ?")
            params.append(status)

        if not update_fields:
            return jsonify(envelope(None, "No valid fields to update", 400, False)), 400

        update_fields.append("updated_at = CURRENT_TIMESTAMP")
        params.append(product_id)

        query = f"UPDATE food_trade_weekly_products SET {', '.join(update_fields)} WHERE id = ?"
        cursor.execute(query, tuple(params))
        conn.commit()

        return jsonify(envelope(None, "Product updated successfully.", 200)), 200
    except Exception:
        conn.rollback()
        return jsonify(envelope(None, "Internal server error", 500, False)), 500
    finally:
        conn.close()


@food_trade_api.route("/weekly_products/<int:product_id>", methods=["DELETE"])
@jwt_required()
def delete_weekly_product(product_id):
    user_id = get_authenticated_user_id()
    if not check_admin(user_id):
        return jsonify(envelope(None, "Unauthorized", 403, False)), 403

    conn, cursor = db_connection()
    try:
        cursor.execute("SELECT id FROM food_trade_weekly_products WHERE id = ?", (product_id,))
        if not cursor.fetchone():
            return jsonify(envelope(None, "Product not found", 404, False)), 404

        cursor.execute("DELETE FROM food_trade_weekly_products WHERE id = ?", (product_id,))
        conn.commit()
        return jsonify(envelope(None, "Product deleted successfully.", 200)), 200
    except Exception:
        conn.rollback()
        return jsonify(envelope(None, "Internal server error", 500, False)), 500
    finally:
        conn.close()
