import json
import logging

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity

from database import db_connection
from decorators.roles import admin_required
from routes.api_envelope import envelope
from routes.farms.products import (
    PRODUCT_STATS_CACHE_KEY,
    _cache_get,
    _cache_set,
    _ensure_product_type,
    _invalidate_products_cache,
    _normalize_animal_type,
    _normalize_bool,
    _normalize_media_arrays,
    _serialize_product_row,
)


products_admin = Blueprint("products_admin", __name__)
logger = logging.getLogger(__name__)


@products_admin.route("", methods=["POST"])
@products_admin.route("/", methods=["POST"])
@admin_required
def create_product():
    data = request.get_json() or {}
    admin_id = get_jwt_identity()

    title = str(data.get("title") or "").strip()
    description = str(data.get("description") or "").strip()
    category = str(data.get("category") or "").strip()
    category_id = data.get("category_id")
    animal_type = _normalize_animal_type(data.get("animal_type"))
    animal_stage = data.get("animal_stage")

    try:
        price = float(data.get("price", 0))
        quantity = int(data.get("quantity", 0))
        weight_per_unit = float(data.get("weight_per_unit", 1.0))
        rating = float(data.get("rating", 4.0))
        discount_percentage = int(data.get("discount_percentage")) if data.get("discount_percentage") is not None else None
    except (TypeError, ValueError):
        return jsonify(envelope(None, "Invalid numeric fields", 400, False)), 400

    if not title:
        return jsonify(envelope(None, "title is required", 400, False)), 400
    if price < 0 or quantity < 0:
        return jsonify(envelope(None, "price and quantity must be non-negative", 400, False)), 400
    if category_id not in (None, ""):
        try:
            category_id = int(category_id)
        except (TypeError, ValueError):
            return jsonify(envelope(None, "category_id must be an integer", 400, False)), 400

    image_url, image_urls, video_urls, media_error = _normalize_media_arrays(data)
    if media_error:
        return jsonify(envelope(None, media_error, 400, False)), 400

    is_alive = _normalize_bool(data.get("is_alive") if "is_alive" in data else data.get("is_live"), False)
    is_fresh = _normalize_bool(data.get("is_fresh"), True)

    try:
        conn, cursor = db_connection()
        animal_type = _ensure_product_type(cursor, animal_type)
        cursor.execute(
            """
            INSERT INTO Products (
                user_id, title, description, price, quantity, category_id, category,
                image_url, image_urls, video_urls,
                weight_per_unit, rating, discount_percentage,
                animal_type, animal_stage, is_alive, is_fresh
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(admin_id),
                title,
                description,
                price,
                quantity,
                category_id if category_id not in (None, "") else None,
                category,
                image_url,
                json.dumps(image_urls),
                json.dumps(video_urls),
                weight_per_unit,
                rating,
                discount_percentage,
                animal_type,
                animal_stage,
                1 if is_alive else 0,
                1 if is_fresh else 0,
            ),
        )
        product_id = cursor.lastrowid
        conn.commit()

        cursor.execute(
            """
            SELECT
                p.id,
                p.title,
                p.description,
                p.price,
                p.quantity,
                p.category_id,
                COALESCE(c.name, p.category) AS category,
                p.image_url,
                p.image_urls,
                p.video_urls,
                p.weight_per_unit,
                p.rating,
                p.discount_percentage,
                p.animal_type,
                p.animal_stage,
                p.is_alive,
                p.is_fresh,
                p.created_at,
                p.updated_at
            FROM Products p
            LEFT JOIN Categories c ON c.id = p.category_id
            WHERE p.id = ?
            """,
            (product_id,),
        )
        row = cursor.fetchone()
        conn.close()

        payload = _serialize_product_row(row)
        _invalidate_products_cache(product_id=product_id)
        return jsonify(envelope(payload, "Product created", 201)), 201
    except Exception as e:
        logger.exception("Failed to create product")
        return jsonify(envelope(None, f"Error: {e}", 500, False)), 500


@products_admin.route("/<int:product_id>", methods=["PUT"])
@admin_required
def update_product(product_id):
    data = request.get_json() or {}

    try:
        conn, cursor = db_connection()
        cursor.execute("SELECT * FROM Products WHERE id = ?", (product_id,))
        existing = cursor.fetchone()
        if not existing:
            conn.close()
            return jsonify(envelope(None, "Product not found", 404, False)), 404
    except Exception as e:
        logger.exception("Failed to read product %s before update", product_id)
        return jsonify(envelope(None, f"Error: {e}", 500, False)), 500

    title = str(data.get("title", existing["title"]) or "").strip()
    description = str(data.get("description", existing["description"] or "")).strip()
    category = str(data.get("category", existing["category"] or "")).strip()
    category_id = data.get("category_id", existing["category_id"])
    animal_type = _normalize_animal_type(data.get("animal_type", existing["animal_type"]))
    animal_stage = data.get("animal_stage", existing["animal_stage"])

    try:
        price = float(data.get("price", existing["price"]))
        quantity = int(data.get("quantity", existing["quantity"]))
        weight_per_unit = float(data.get("weight_per_unit", existing["weight_per_unit"]))
        rating = float(data.get("rating", existing["rating"] if existing["rating"] is not None else 4.0))
        discount_percentage_raw = data.get("discount_percentage", existing["discount_percentage"])
        discount_percentage = int(discount_percentage_raw) if discount_percentage_raw is not None else None
    except (TypeError, ValueError):
        conn.close()
        return jsonify(envelope(None, "Invalid numeric fields", 400, False)), 400

    if not title:
        conn.close()
        return jsonify(envelope(None, "title is required", 400, False)), 400
    if price < 0 or quantity < 0:
        conn.close()
        return jsonify(envelope(None, "price and quantity must be non-negative", 400, False)), 400
    if category_id not in (None, ""):
        try:
            category_id = int(category_id)
        except (TypeError, ValueError):
            conn.close()
            return jsonify(envelope(None, "category_id must be an integer", 400, False)), 400

    merged_media_payload = dict(data)
    if "image_url" not in merged_media_payload:
        merged_media_payload["image_url"] = existing["image_url"]
    if "image_urls" not in merged_media_payload:
        merged_media_payload["image_urls"] = existing["image_urls"]
    if "video_urls" not in merged_media_payload:
        merged_media_payload["video_urls"] = existing["video_urls"]

    image_url, image_urls, video_urls, media_error = _normalize_media_arrays(merged_media_payload)
    if media_error:
        conn.close()
        return jsonify(envelope(None, media_error, 400, False)), 400

    is_alive = _normalize_bool(
        data.get("is_alive", data.get("is_live", existing["is_alive"])),
        bool(existing["is_alive"]),
    )
    is_fresh = _normalize_bool(data.get("is_fresh", existing["is_fresh"]), bool(existing["is_fresh"]))

    try:
        animal_type = _ensure_product_type(cursor, animal_type)
        cursor.execute(
            """
            UPDATE Products
            SET
                title = ?,
                description = ?,
                price = ?,
                quantity = ?,
                category_id = ?,
                category = ?,
                image_url = ?,
                image_urls = ?,
                video_urls = ?,
                weight_per_unit = ?,
                rating = ?,
                discount_percentage = ?,
                animal_type = ?,
                animal_stage = ?,
                is_alive = ?,
                is_fresh = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                title,
                description,
                price,
                quantity,
                category_id if category_id not in (None, "") else None,
                category,
                image_url,
                json.dumps(image_urls),
                json.dumps(video_urls),
                weight_per_unit,
                rating,
                discount_percentage,
                animal_type,
                animal_stage,
                1 if is_alive else 0,
                1 if is_fresh else 0,
                product_id,
            ),
        )
        conn.commit()

        cursor.execute(
            """
            SELECT
                p.id,
                p.title,
                p.description,
                p.price,
                p.quantity,
                p.category_id,
                COALESCE(c.name, p.category) AS category,
                p.image_url,
                p.image_urls,
                p.video_urls,
                p.weight_per_unit,
                p.rating,
                p.discount_percentage,
                p.animal_type,
                p.animal_stage,
                p.is_alive,
                p.is_fresh,
                p.created_at,
                p.updated_at
            FROM Products p
            LEFT JOIN Categories c ON c.id = p.category_id
            WHERE p.id = ?
            """,
            (product_id,),
        )
        row = cursor.fetchone()
        conn.close()

        payload = _serialize_product_row(row)
        _invalidate_products_cache(product_id=product_id)
        return jsonify(envelope(payload, "Product updated", 200)), 200
    except Exception as e:
        conn.close()
        logger.exception("Failed to update product %s", product_id)
        return jsonify(envelope(None, f"Error: {e}", 500, False)), 500


@products_admin.route("/<int:product_id>", methods=["DELETE"])
@admin_required
def delete_product(product_id):
    try:
        conn, cursor = db_connection()
        cursor.execute("DELETE FROM Products WHERE id = ?", (product_id,))
        conn.commit()
        deleted = cursor.rowcount
        conn.close()
        if deleted == 0:
            return jsonify(envelope(None, "Product not found", 404, False)), 404

        _invalidate_products_cache(product_id=product_id)
        return jsonify(envelope({"id": product_id}, "Product deleted", 200)), 200
    except Exception as e:
        logger.exception("Failed to delete product %s", product_id)
        return jsonify(envelope(None, f"Error: {e}", 500, False)), 500


@products_admin.route("", methods=["DELETE"])
@products_admin.route("/", methods=["DELETE"])
@admin_required
def bulk_delete_products():
    data = request.get_json(silent=True) or {}
    ids = data.get("ids")

    try:
        conn, cursor = db_connection()
        if isinstance(ids, list) and ids:
            valid_ids = []
            for raw_id in ids:
                try:
                    valid_ids.append(int(raw_id))
                except (TypeError, ValueError):
                    continue
            if not valid_ids:
                conn.close()
                return jsonify(envelope(None, "ids must contain valid product ids", 400, False)), 400

            placeholders = ",".join("?" for _ in valid_ids)
            cursor.execute(f"DELETE FROM Products WHERE id IN ({placeholders})", tuple(valid_ids))
            deleted_count = cursor.rowcount
            conn.commit()
            conn.close()
            _invalidate_products_cache()
            return jsonify(envelope({"deleted": deleted_count, "ids": valid_ids}, "Products deleted", 200)), 200

        cursor.execute("DELETE FROM Products")
        deleted_count = cursor.rowcount
        conn.commit()
        conn.close()
        _invalidate_products_cache()
        return jsonify(envelope({"deleted": deleted_count}, "All products deleted", 200)), 200
    except Exception as e:
        logger.exception("Failed to bulk delete products")
        return jsonify(envelope(None, f"Error: {e}", 500, False)), 500


@products_admin.route("/stats/overview", methods=["GET"])
@admin_required
def product_stats_overview():
    cached = _cache_get(PRODUCT_STATS_CACHE_KEY)
    if cached is not None:
        return jsonify(envelope(cached, "Product stats fetched", 200)), 200

    try:
        conn, cursor = db_connection()
        cursor.execute("SELECT COUNT(*) AS c FROM Products")
        total_products = int(cursor.fetchone()["c"] or 0)

        cursor.execute("SELECT COUNT(*) AS c FROM Products WHERE quantity > 10")
        in_stock = int(cursor.fetchone()["c"] or 0)

        cursor.execute("SELECT COUNT(*) AS c FROM Products WHERE quantity BETWEEN 1 AND 10")
        low_stock = int(cursor.fetchone()["c"] or 0)

        cursor.execute("SELECT COUNT(*) AS c FROM Products WHERE quantity <= 0")
        out_of_stock = int(cursor.fetchone()["c"] or 0)

        cursor.execute("SELECT COALESCE(SUM(price * quantity), 0) AS v FROM Products")
        inventory_value = float(cursor.fetchone()["v"] or 0)
        conn.close()

        payload = {
            "totalProducts": total_products,
            "inStock": in_stock,
            "lowStock": low_stock,
            "outOfStock": out_of_stock,
            "inventoryValue": round(inventory_value, 2),
        }
        _cache_set(PRODUCT_STATS_CACHE_KEY, payload)
        return jsonify(envelope(payload, "Product stats fetched", 200)), 200
    except Exception as e:
        logger.exception("Failed to fetch product stats")
        return jsonify(envelope(None, f"Error: {e}", 500, False)), 500
