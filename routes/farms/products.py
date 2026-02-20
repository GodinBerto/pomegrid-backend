import json
import logging
from urllib.parse import urlparse

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity

from database import db_connection
from decorators.roles import admin_required
from extensions.redis_client import get_redis_client
from routes.api_envelope import build_meta, envelope, parse_pagination


products = Blueprint("products", __name__)
logger = logging.getLogger(__name__)

PRODUCT_CACHE_KEY_PREFIX = "farms:products:item"
PRODUCT_LIST_CACHE_KEY_PREFIX = "farms:products:list"
PRODUCT_STATS_CACHE_KEY = "farms:products:stats:overview"


def _cache_get(key):
    try:
        redis_client = get_redis_client()
        value = redis_client.get(key)
        return json.loads(value) if value else None
    except Exception as e:
        logger.warning("Redis unavailable, skipping products cache read: %s", e)
        return None


def _cache_set(key, payload, ttl=60):
    try:
        redis_client = get_redis_client()
        redis_client.setex(key, ttl, json.dumps(payload))
    except Exception as e:
        logger.warning("Redis unavailable, skipping products cache write: %s", e)


def _cache_delete(*keys):
    if not keys:
        return
    try:
        redis_client = get_redis_client()
        redis_client.delete(*keys)
    except Exception as e:
        logger.warning("Redis unavailable, skipping products cache delete: %s", e)


def _cache_delete_patterns(*patterns):
    try:
        redis_client = get_redis_client()
        keys = []
        for pattern in patterns:
            keys.extend(redis_client.keys(pattern))
        if keys:
            redis_client.delete(*keys)
    except Exception as e:
        logger.warning("Redis unavailable, skipping products cache pattern delete: %s", e)


def _product_cache_key(product_id):
    return f"{PRODUCT_CACHE_KEY_PREFIX}:{product_id}"


def _product_list_cache_key(raw_query):
    return f"{PRODUCT_LIST_CACHE_KEY_PREFIX}:{raw_query or 'default'}"


def _is_valid_url(value):
    parsed = urlparse(str(value or "").strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _normalize_bool(value, default=False):
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes"}:
        return True
    if normalized in {"0", "false", "no"}:
        return False
    return bool(default)


def _normalize_media_arrays(payload):
    image_url = str(payload.get("image_url") or "").strip()
    image_urls = payload.get("image_urls")
    video_urls = payload.get("video_urls")

    if image_urls is None:
        image_urls_list = [image_url] if image_url else []
    elif isinstance(image_urls, list):
        image_urls_list = [str(item).strip() for item in image_urls if str(item).strip()]
    elif isinstance(image_urls, str):
        image_urls_list = [image_urls.strip()] if image_urls.strip() else []
    else:
        image_urls_list = []

    deduped_images = []
    seen_images = set()
    for item in image_urls_list:
        if item and item not in seen_images:
            seen_images.add(item)
            deduped_images.append(item)

    if image_url and image_url not in seen_images:
        deduped_images.insert(0, image_url)

    if video_urls is None:
        video_urls_list = []
    elif isinstance(video_urls, list):
        video_urls_list = [str(item).strip() for item in video_urls if str(item).strip()]
    elif isinstance(video_urls, str):
        video_urls_list = [video_urls.strip()] if video_urls.strip() else []
    else:
        video_urls_list = []

    deduped_videos = []
    seen_videos = set()
    for item in video_urls_list:
        if item and item not in seen_videos:
            seen_videos.add(item)
            deduped_videos.append(item)

    invalid_video_urls = [item for item in deduped_videos if not _is_valid_url(item)]
    if invalid_video_urls:
        return None, None, None, f"Invalid video URL(s): {invalid_video_urls}"

    if not deduped_images:
        return None, None, None, "At least one image is required (image_url or image_urls)."

    primary_image = deduped_images[0]
    return primary_image, deduped_images, deduped_videos, None


def _serialize_product_row(row):
    product = dict(row)
    parsed_images = []
    parsed_videos = []

    if product.get("image_urls"):
        try:
            decoded = json.loads(product["image_urls"])
            if isinstance(decoded, list):
                parsed_images = [str(item).strip() for item in decoded if str(item).strip()]
        except Exception:
            parsed_images = []

    if product.get("image_url") and product["image_url"] not in parsed_images:
        parsed_images.insert(0, product["image_url"])
    if parsed_images:
        product["image_url"] = parsed_images[0]
    product["image_urls"] = parsed_images

    if product.get("video_urls"):
        try:
            decoded_videos = json.loads(product["video_urls"])
            if isinstance(decoded_videos, list):
                parsed_videos = [str(item).strip() for item in decoded_videos if str(item).strip()]
        except Exception:
            parsed_videos = []
    product["video_urls"] = parsed_videos

    product["quantity"] = int(product.get("quantity") or 0)
    product["price"] = float(product.get("price") or 0)
    product["weight_per_unit"] = float(product.get("weight_per_unit") or 0)
    product["rating"] = float(product.get("rating") or 0)
    product["discount_percentage"] = int(product.get("discount_percentage") or 0) if product.get("discount_percentage") is not None else None
    product["is_alive"] = bool(product.get("is_alive"))
    product["is_fresh"] = bool(product.get("is_fresh"))
    return product


def _invalidate_products_cache(product_id=None):
    keys = [PRODUCT_STATS_CACHE_KEY]
    if product_id is not None:
        keys.append(_product_cache_key(product_id))
    _cache_delete(*keys)
    _cache_delete_patterns(f"{PRODUCT_LIST_CACHE_KEY_PREFIX}:*")


@products.route("", methods=["GET"])
@products.route("/", methods=["GET"])
def list_products():
    page, per_page, offset = parse_pagination(request.args)

    search = str(request.args.get("search") or "").strip()
    category = str(request.args.get("category") or "").strip()
    stock_status = str(request.args.get("stock_status") or "").strip().lower()
    sort_by = str(request.args.get("sort_by") or "created_at").strip().lower()
    sort_dir = str(request.args.get("sort_dir") or "desc").strip().lower()

    if stock_status and stock_status not in {"in-stock", "low-stock", "out-of-stock"}:
        return jsonify(envelope(None, "stock_status must be in-stock|low-stock|out-of-stock", 400, False)), 400

    sort_fields = {
        "name": "p.title",
        "price": "p.price",
        "stock": "p.quantity",
        "created_at": "p.created_at",
    }
    order_field = sort_fields.get(sort_by, "p.created_at")
    direction = "ASC" if sort_dir == "asc" else "DESC"

    cache_key = _product_list_cache_key(request.query_string.decode("utf-8"))
    cached = _cache_get(cache_key)
    if cached is not None:
        return jsonify(envelope(cached.get("items", []), "Products fetched", 200, True, cached.get("meta"))), 200

    where = ["1=1"]
    params = []

    if search:
        like = f"%{search}%"
        where.append("(LOWER(p.title) LIKE LOWER(?) OR LOWER(COALESCE(p.description, '')) LIKE LOWER(?))")
        params.extend([like, like])

    if category:
        where.append("(LOWER(COALESCE(c.name, p.category, '')) = LOWER(?) OR CAST(p.category_id AS TEXT) = ?)")
        params.extend([category, category])

    if stock_status == "in-stock":
        where.append("p.quantity > 10")
    elif stock_status == "low-stock":
        where.append("p.quantity BETWEEN 1 AND 10")
    elif stock_status == "out-of-stock":
        where.append("p.quantity <= 0")

    where_sql = " AND ".join(where)

    try:
        conn, cursor = db_connection()
        cursor.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM Products p
            LEFT JOIN Categories c ON c.id = p.category_id
            WHERE {where_sql}
            """,
            tuple(params),
        )
        total = int(cursor.fetchone()["total"] or 0)

        query_params = list(params) + [per_page, offset]
        cursor.execute(
            f"""
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
            WHERE {where_sql}
            ORDER BY {order_field} {direction}, p.id DESC
            LIMIT ? OFFSET ?
            """,
            tuple(query_params),
        )
        rows = cursor.fetchall()
        conn.close()

        items = [_serialize_product_row(row) for row in rows]
        meta = build_meta(page, per_page, total)
        _cache_set(cache_key, {"items": items, "meta": meta})
        return jsonify(envelope(items, "Products fetched", 200, True, meta)), 200
    except Exception as e:
        logger.exception("Failed to list products")
        return jsonify(envelope(None, f"Error: {e}", 500, False)), 500


@products.route("/<int:product_id>", methods=["GET"])
def get_product(product_id):
    cache_key = _product_cache_key(product_id)
    cached = _cache_get(cache_key)
    if cached is not None:
        return jsonify(envelope(cached, "Product fetched", 200)), 200

    try:
        conn, cursor = db_connection()
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
        if not row:
            return jsonify(envelope(None, "Product not found", 404, False)), 404
        payload = _serialize_product_row(row)
        _cache_set(cache_key, payload)
        return jsonify(envelope(payload, "Product fetched", 200)), 200
    except Exception as e:
        logger.exception("Failed to get product %s", product_id)
        return jsonify(envelope(None, f"Error: {e}", 500, False)), 500


@products.route("", methods=["POST"])
@products.route("/", methods=["POST"])
@admin_required
def create_product():
    data = request.get_json() or {}
    admin_id = get_jwt_identity()

    title = str(data.get("title") or "").strip()
    description = str(data.get("description") or "").strip()
    category = str(data.get("category") or "").strip()
    category_id = data.get("category_id")
    animal_type = data.get("animal_type")
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


@products.route("/<int:product_id>", methods=["PUT"])
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
    animal_type = data.get("animal_type", existing["animal_type"])
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


@products.route("/<int:product_id>", methods=["DELETE"])
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


@products.route("", methods=["DELETE"])
@products.route("/", methods=["DELETE"])
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


@products.route("/stats/overview", methods=["GET"])
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
