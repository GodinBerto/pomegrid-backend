import json

from flask import jsonify, request

from database import db_connection
from routes.api_envelope import build_meta, envelope, parse_pagination
from routes.farms.products import _delete_product_with_dependencies, _invalidate_products_cache

from .common import (
    _current_user_id,
    _format_currency,
    _normalize_account_type,
    _safe_text,
    connect_api,
    logger,
)
from .profiles import _require_connect_profile


def _serialize_listing_row(row):
    price = float(row["price"] or 0)
    quantity = int(row["quantity"] or 0)
    return {
        "id": int(row["id"]),
        "name": row["title"],
        "title": row["title"],
        "category": _safe_text(row["category"]),
        "price": price,
        "formatted_price": _format_currency(price),
        "unit": "kg",
        "quantity": quantity,
        "formatted_quantity": f"{quantity:,}",
        "origin": _safe_text(row["country"]),
        "description": _safe_text(row["description"]),
        "image_url": row["image_url"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


@connect_api.route("/listings", methods=["GET"])
def list_connect_listings():
    user_id = _current_user_id()
    page, per_page, offset = parse_pagination(request.args)

    try:
        conn, cursor = db_connection()
        profile_row = _require_connect_profile(cursor, user_id)
        if not profile_row:
            conn.close()
            return jsonify(envelope(None, "Connect profile not found", 404, False)), 404

        cursor.execute("SELECT COUNT(*) AS total FROM Products WHERE user_id = ? AND COALESCE(is_active, 1) = 1", (user_id,))
        total = int(cursor.fetchone()["total"] or 0)
        cursor.execute(
            """
            SELECT
                p.id,
                p.title,
                p.category,
                p.description,
                p.price,
                p.quantity,
                p.image_url,
                p.created_at,
                p.updated_at,
                cp.country
            FROM Products p
            LEFT JOIN ConnectProfiles cp ON cp.user_id = p.user_id
            WHERE p.user_id = ?
              AND COALESCE(p.is_active, 1) = 1
            ORDER BY p.created_at DESC, p.id DESC
            LIMIT ? OFFSET ?
            """,
            (user_id, per_page, offset),
        )
        items = [_serialize_listing_row(row) for row in cursor.fetchall()]
        conn.close()

        meta = build_meta(page, per_page, total)
        return jsonify(envelope(items, "Listings fetched", 200, True, meta)), 200
    except Exception as e:
        logger.exception("Failed to list connect listings for %s", user_id)
        return jsonify(envelope(None, f"Error: {e}", 500, False)), 500


@connect_api.route("/listings", methods=["POST"])
def create_connect_listing():
    user_id = _current_user_id()
    data = request.get_json() or {}

    title = _safe_text(data.get("title") or data.get("name"))
    category = _safe_text(data.get("category"))
    description = _safe_text(data.get("description"))
    image_url = _safe_text(data.get("image_url"))

    try:
        price = float(data.get("price", 0))
        quantity = int(data.get("quantity", 0))
    except (TypeError, ValueError):
        return jsonify(envelope(None, "price and quantity must be valid numbers", 400, False)), 400

    if not title:
        return jsonify(envelope(None, "title is required", 400, False)), 400
    if price < 0 or quantity < 0:
        return jsonify(envelope(None, "price and quantity must be non-negative", 400, False)), 400

    try:
        conn, cursor = db_connection()
        profile_row = _require_connect_profile(cursor, user_id)
        if not profile_row:
            conn.close()
            return jsonify(envelope(None, "Connect profile not found", 404, False)), 404
        if _normalize_account_type(profile_row["account_type"]) != "farmer":
            conn.close()
            return jsonify(envelope(None, "Only farmers can manage listings", 403, False)), 403

        cursor.execute(
            """
            INSERT INTO Products (
                user_id,
                title,
                category,
                description,
                price,
                quantity,
                image_url,
                image_urls,
                video_urls
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                title,
                category,
                description,
                price,
                quantity,
                image_url or None,
                json.dumps([image_url]) if image_url else json.dumps([]),
                json.dumps([]),
            ),
        )
        listing_id = cursor.lastrowid
        conn.commit()

        cursor.execute(
            """
            SELECT
                p.id,
                p.title,
                p.category,
                p.description,
                p.price,
                p.quantity,
                p.image_url,
                p.created_at,
                p.updated_at,
                cp.country
            FROM Products p
            LEFT JOIN ConnectProfiles cp ON cp.user_id = p.user_id
            WHERE p.id = ?
            LIMIT 1
            """,
            (listing_id,),
        )
        row = cursor.fetchone()
        conn.close()

        _invalidate_products_cache(product_id=listing_id)
        return jsonify(envelope(_serialize_listing_row(row), "Listing created", 201)), 201
    except Exception as e:
        logger.exception("Failed to create listing for %s", user_id)
        return jsonify(envelope(None, f"Error: {e}", 500, False)), 500


@connect_api.route("/listings/<int:listing_id>", methods=["PUT"])
def update_connect_listing(listing_id):
    user_id = _current_user_id()
    data = request.get_json() or {}

    try:
        conn, cursor = db_connection()
        profile_row = _require_connect_profile(cursor, user_id)
        if not profile_row:
            conn.close()
            return jsonify(envelope(None, "Connect profile not found", 404, False)), 404
        if _normalize_account_type(profile_row["account_type"]) != "farmer":
            conn.close()
            return jsonify(envelope(None, "Only farmers can manage listings", 403, False)), 403

        cursor.execute("SELECT id, title, category, description, price, quantity, image_url FROM Products WHERE id = ? AND user_id = ? AND COALESCE(is_active, 1) = 1 LIMIT 1", (int(listing_id), user_id))
        existing = cursor.fetchone()
        if not existing:
            conn.close()
            return jsonify(envelope(None, "Listing not found", 404, False)), 404

        title = _safe_text(data.get("title") or data.get("name")) or existing["title"]
        category = _safe_text(data.get("category")) or _safe_text(existing["category"])
        description = _safe_text(data.get("description")) if "description" in data else _safe_text(existing["description"])
        image_url = _safe_text(data.get("image_url")) if "image_url" in data else _safe_text(existing["image_url"])

        try:
            price = float(data.get("price", existing["price"]))
            quantity = int(data.get("quantity", existing["quantity"]))
        except (TypeError, ValueError):
            conn.close()
            return jsonify(envelope(None, "price and quantity must be valid numbers", 400, False)), 400

        if not title:
            conn.close()
            return jsonify(envelope(None, "title is required", 400, False)), 400
        if price < 0 or quantity < 0:
            conn.close()
            return jsonify(envelope(None, "price and quantity must be non-negative", 400, False)), 400

        cursor.execute(
            """
            UPDATE Products
            SET
                title = ?,
                category = ?,
                description = ?,
                price = ?,
                quantity = ?,
                image_url = ?,
                image_urls = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND user_id = ?
            """,
            (
                title,
                category,
                description,
                price,
                quantity,
                image_url or None,
                json.dumps([image_url]) if image_url else json.dumps([]),
                int(listing_id),
                user_id,
            ),
        )
        conn.commit()
        cursor.execute(
            """
            SELECT
                p.id,
                p.title,
                p.category,
                p.description,
                p.price,
                p.quantity,
                p.image_url,
                p.created_at,
                p.updated_at,
                cp.country
            FROM Products p
            LEFT JOIN ConnectProfiles cp ON cp.user_id = p.user_id
            WHERE p.id = ?
            LIMIT 1
            """,
            (int(listing_id),),
        )
        row = cursor.fetchone()
        conn.close()

        _invalidate_products_cache(product_id=listing_id)
        return jsonify(envelope(_serialize_listing_row(row), "Listing updated", 200)), 200
    except Exception as e:
        logger.exception("Failed to update listing %s for %s", listing_id, user_id)
        return jsonify(envelope(None, f"Error: {e}", 500, False)), 500


@connect_api.route("/listings/<int:listing_id>", methods=["DELETE"])
def delete_connect_listing(listing_id):
    user_id = _current_user_id()

    try:
        conn, cursor = db_connection()
        profile_row = _require_connect_profile(cursor, user_id)
        if not profile_row:
            conn.close()
            return jsonify(envelope(None, "Connect profile not found", 404, False)), 404
        if _normalize_account_type(profile_row["account_type"]) != "farmer":
            conn.close()
            return jsonify(envelope(None, "Only farmers can manage listings", 403, False)), 403

        cursor.execute("SELECT id FROM Products WHERE id = ? AND user_id = ? AND COALESCE(is_active, 1) = 1 LIMIT 1", (int(listing_id), user_id))
        if not cursor.fetchone():
            conn.close()
            return jsonify(envelope(None, "Listing not found", 404, False)), 404

        delete_result = _delete_product_with_dependencies(cursor, int(listing_id), user_id)
        conn.commit()
        conn.close()

        _invalidate_products_cache(product_id=listing_id)
        payload = {"id": int(listing_id), "reference_counts": delete_result["reference_counts"]}
        if delete_result.get("archived"):
            payload["archived"] = True
            return jsonify(envelope(payload, "Listing archived because it has order history.", 200)), 200
        return jsonify(envelope(payload, "Listing deleted", 200)), 200
    except Exception as e:
        logger.exception("Failed to delete listing %s for %s", listing_id, user_id)
        return jsonify(envelope(None, f"Error: {e}", 500, False)), 500
