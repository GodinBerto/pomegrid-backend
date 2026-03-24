import json
import logging
from urllib.parse import urlparse

from flask import Blueprint, g, jsonify, request

from database import db_connection
from decorators.rate_limit import rate_limit
from decorators.roles import ROLE_USER, ROLE_WORKER, role_required
from extensions.redis_client import get_redis_client
from routes.api_envelope import build_meta, envelope, parse_pagination


products = Blueprint("products", __name__)
logger = logging.getLogger(__name__)

PRODUCT_CACHE_KEY_PREFIX = "farms:products:item"
PRODUCT_LIST_CACHE_KEY_PREFIX = "farms:products:list"
PRODUCT_STATS_CACHE_KEY = "farms:products:stats:overview"
FEATURED_PRODUCT_LIST_CACHE_KEY_PREFIX = "farms:products:featured"


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


def _featured_product_list_cache_key(raw_query):
    return f"{FEATURED_PRODUCT_LIST_CACHE_KEY_PREFIX}:{raw_query or 'default'}"


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


def _normalize_animal_type(value):
    normalized = str(value or "").strip()
    return normalized or None


def _ensure_product_type(cursor, animal_type):
    normalized = _normalize_animal_type(animal_type)
    if not normalized:
        return None
    try:
        cursor.execute(
            """
            INSERT OR IGNORE INTO ProductTypes (id, name)
            VALUES (?, ?)
            """,
            (normalized, normalized),
        )
    except Exception as e:
        if "no such table" in str(e).lower() and "producttypes" in str(e).lower():
            logger.warning("ProductTypes table missing; skipping ProductTypes sync")
        else:
            raise
    return normalized


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
    product["is_featured"] = bool(product.get("is_featured"))
    product["is_active"] = bool(product.get("is_active", True))
    return product


def _invalidate_products_cache(product_id=None):
    keys = [PRODUCT_STATS_CACHE_KEY]
    if product_id is not None:
        keys.append(_product_cache_key(product_id))
    _cache_delete(*keys)
    _cache_delete_patterns(f"{PRODUCT_LIST_CACHE_KEY_PREFIX}:*")
    _cache_delete_patterns(f"{FEATURED_PRODUCT_LIST_CACHE_KEY_PREFIX}:*")


def _fetch_product_feedback_summary(cursor, product_id):
    cursor.execute(
        """
        SELECT
            COUNT(*) AS total_feedback,
            ROUND(AVG(rating), 2) AS average_rating
        FROM ProductFeedback
        WHERE product_id = ?
        """,
        (product_id,),
    )
    row = cursor.fetchone()
    total_feedback = int((row["total_feedback"] if row else 0) or 0)
    average_rating = float((row["average_rating"] if row else 0) or 0)
    return {
        "total_feedback": total_feedback,
        "average_rating": average_rating,
    }


def _refresh_product_rating(cursor, product_id):
    summary = _fetch_product_feedback_summary(cursor, product_id)
    next_rating = summary["average_rating"] if summary["total_feedback"] > 0 else 0
    cursor.execute(
        """
        UPDATE Products
        SET rating = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (next_rating, product_id),
    )
    return summary


def _get_product_reference_counts(cursor, product_id):
    counts = {}
    for table_name in ("Cart", "ProductFeedback", "OrderItems"):
        cursor.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM {table_name}
            WHERE product_id = ?
            """,
            (product_id,),
        )
        counts[table_name] = int(cursor.fetchone()["total"] or 0)
    return counts


def _delete_product_with_dependencies(cursor, product_id, owner_user_id=None):
    reference_counts = _get_product_reference_counts(cursor, product_id)
    cursor.execute("DELETE FROM Cart WHERE product_id = ?", (product_id,))
    if reference_counts["OrderItems"] > 0:
        if owner_user_id is None:
            cursor.execute(
                """
                UPDATE Products
                SET is_active = 0,
                    is_featured = 0,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (product_id,),
            )
        else:
            cursor.execute(
                """
                UPDATE Products
                SET is_active = 0,
                    is_featured = 0,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND user_id = ?
                """,
                (product_id, owner_user_id),
            )
        return {
            "deleted": False,
            "archived": int(cursor.rowcount or 0) > 0,
            "blocked_by_orders": False,
            "reference_counts": reference_counts,
        }

    cursor.execute("DELETE FROM ProductFeedback WHERE product_id = ?", (product_id,))
    if owner_user_id is None:
        cursor.execute("DELETE FROM Products WHERE id = ?", (product_id,))
    else:
        cursor.execute("DELETE FROM Products WHERE id = ? AND user_id = ?", (product_id, owner_user_id))

    return {
        "deleted": int(cursor.rowcount or 0) > 0,
        "archived": False,
        "blocked_by_orders": False,
        "reference_counts": reference_counts,
    }


def _serialize_product_feedback_row(row):
    feedback = dict(row)
    feedback["id"] = int(feedback.get("id") or 0)
    feedback["product_id"] = int(feedback.get("product_id") or 0)
    feedback["user_id"] = int(feedback.get("user_id") or 0)
    feedback["rating"] = int(feedback.get("rating") or 0)
    feedback["feedback"] = str(feedback.get("feedback") or "").strip()
    feedback["user_name"] = str(feedback.get("user_name") or "Customer").strip() or "Customer"
    return feedback


def _fetch_product_feedback_row(cursor, feedback_id):
    cursor.execute(
        """
        SELECT
            pf.id,
            pf.product_id,
            pf.user_id,
            pf.rating,
            pf.feedback,
            pf.created_at,
            pf.updated_at,
            COALESCE(NULLIF(TRIM(u.full_name), ''), NULLIF(TRIM(u.email), ''), 'Customer') AS user_name
        FROM ProductFeedback pf
        LEFT JOIN Users u ON u.id = pf.user_id
        WHERE pf.id = ?
        """,
        (feedback_id,),
    )
    row = cursor.fetchone()
    return _serialize_product_feedback_row(row) if row else None


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

    where = ["COALESCE(p.is_active, 1) = 1"]
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
                p.is_featured,
                p.is_active,
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


@products.route("/featured", methods=["GET"])
def list_featured_products():
    page, per_page, offset = parse_pagination(request.args)

    search = str(request.args.get("search") or "").strip()
    category = str(request.args.get("category") or "").strip()

    cache_key = _featured_product_list_cache_key(request.query_string.decode("utf-8"))
    cached = _cache_get(cache_key)
    if cached is not None:
        return jsonify(envelope(cached.get("items", []), "Featured products fetched", 200, True, cached.get("meta"))), 200

    where = ["COALESCE(p.is_active, 1) = 1", "p.is_featured = 1"]
    params = []

    if search:
        like = f"%{search}%"
        where.append("(LOWER(p.title) LIKE LOWER(?) OR LOWER(COALESCE(p.description, '')) LIKE LOWER(?))")
        params.extend([like, like])

    if category:
        where.append("(LOWER(COALESCE(c.name, p.category, '')) = LOWER(?) OR CAST(p.category_id AS TEXT) = ?)")
        params.extend([category, category])

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
                p.is_featured,
                p.is_active,
                p.animal_type,
                p.animal_stage,
                p.is_alive,
                p.is_fresh,
                p.created_at,
                p.updated_at
            FROM Products p
            LEFT JOIN Categories c ON c.id = p.category_id
            WHERE {where_sql}
            ORDER BY COALESCE(p.updated_at, p.created_at) DESC, p.id DESC
            LIMIT ? OFFSET ?
            """,
            tuple(query_params),
        )
        rows = cursor.fetchall()
        conn.close()

        items = [_serialize_product_row(row) for row in rows]
        meta = build_meta(page, per_page, total)
        _cache_set(cache_key, {"items": items, "meta": meta})
        return jsonify(envelope(items, "Featured products fetched", 200, True, meta)), 200
    except Exception as e:
        logger.exception("Failed to list featured products")
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
                p.is_featured,
                p.is_active,
                p.animal_type,
                p.animal_stage,
                p.is_alive,
                p.is_fresh,
                p.created_at,
                p.updated_at
            FROM Products p
            LEFT JOIN Categories c ON c.id = p.category_id
            WHERE p.id = ?
              AND COALESCE(p.is_active, 1) = 1
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


@products.route("/<int:product_id>/feedback", methods=["GET"])
def list_product_feedback(product_id):
    page, per_page, offset = parse_pagination(request.args)

    try:
        conn, cursor = db_connection()
        cursor.execute("SELECT id FROM Products WHERE id = ? AND COALESCE(is_active, 1) = 1", (product_id,))
        if not cursor.fetchone():
            conn.close()
            return jsonify(envelope(None, "Product not found", 404, False)), 404

        summary = _fetch_product_feedback_summary(cursor, product_id)
        cursor.execute(
            """
            SELECT
                pf.id,
                pf.product_id,
                pf.user_id,
                pf.rating,
                pf.feedback,
                pf.created_at,
                pf.updated_at,
                COALESCE(NULLIF(TRIM(u.full_name), ''), NULLIF(TRIM(u.email), ''), 'Customer') AS user_name
            FROM ProductFeedback pf
            LEFT JOIN Users u ON u.id = pf.user_id
            WHERE pf.product_id = ?
            ORDER BY COALESCE(pf.updated_at, pf.created_at) DESC, pf.id DESC
            LIMIT ? OFFSET ?
            """,
            (product_id, per_page, offset),
        )
        feedback_rows = cursor.fetchall()
        conn.close()

        items = [_serialize_product_feedback_row(row) for row in feedback_rows]
        meta = build_meta(page, per_page, summary["total_feedback"])
        payload = envelope(items, "Product feedback fetched", 200, True, meta)
        payload["summary"] = summary
        return jsonify(payload), 200
    except Exception as e:
        logger.exception("Failed to list product feedback for %s", product_id)
        return jsonify(envelope(None, f"Error: {e}", 500, False)), 500


@products.route("/<int:product_id>/feedback", methods=["POST"])
@role_required(ROLE_USER, ROLE_WORKER)
@rate_limit("product-feedback-submit", limit=10, window_seconds=60)
def upsert_product_feedback(product_id):
    data = request.get_json(silent=True) or {}

    try:
        rating = int(data.get("rating"))
    except (TypeError, ValueError):
        return jsonify(envelope(None, "Rating must be a whole number between 1 and 5", 400, False)), 400

    if rating < 1 or rating > 5:
        return jsonify(envelope(None, "Rating must be between 1 and 5", 400, False)), 400

    feedback_text = str(data.get("feedback") or data.get("comment") or "").strip()
    if len(feedback_text) < 3:
        return jsonify(envelope(None, "Feedback must be at least 3 characters long", 400, False)), 400
    if len(feedback_text) > 1000:
        return jsonify(envelope(None, "Feedback must be 1000 characters or fewer", 400, False)), 400

    user_id = int(g.current_user["id"])

    try:
        conn, cursor = db_connection()
        cursor.execute("SELECT id FROM Products WHERE id = ? AND COALESCE(is_active, 1) = 1", (product_id,))
        if not cursor.fetchone():
            conn.close()
            return jsonify(envelope(None, "Product not found", 404, False)), 404

        cursor.execute(
            """
            SELECT id
            FROM ProductFeedback
            WHERE product_id = ? AND user_id = ?
            """,
            (product_id, user_id),
        )
        existing_row = cursor.fetchone()
        is_update = existing_row is not None

        cursor.execute(
            """
            INSERT INTO ProductFeedback (product_id, user_id, rating, feedback)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(product_id, user_id)
            DO UPDATE SET
                rating = excluded.rating,
                feedback = excluded.feedback,
                updated_at = CURRENT_TIMESTAMP
            """,
            (product_id, user_id, rating, feedback_text),
        )

        cursor.execute(
            """
            SELECT id
            FROM ProductFeedback
            WHERE product_id = ? AND user_id = ?
            """,
            (product_id, user_id),
        )
        saved_row = cursor.fetchone()
        feedback_id = int(saved_row["id"])

        summary = _refresh_product_rating(cursor, product_id)
        conn.commit()

        feedback_item = _fetch_product_feedback_row(cursor, feedback_id)
        conn.close()

        _invalidate_products_cache(product_id)

        payload = envelope(
            feedback_item,
            "Feedback updated successfully" if is_update else "Feedback submitted successfully",
            200 if is_update else 201,
            True,
        )
        payload["summary"] = summary
        return jsonify(payload), (200 if is_update else 201)
    except Exception as e:
        logger.exception("Failed to save product feedback for %s", product_id)
        return jsonify(envelope(None, f"Error: {e}", 500, False)), 500
