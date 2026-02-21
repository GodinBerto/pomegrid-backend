import json
import logging

from flask import Blueprint, jsonify, request

from database import db_connection
from extensions.redis_client import get_redis_client
from routes.api_envelope import envelope


categories = Blueprint("categories", __name__)
logger = logging.getLogger(__name__)

CATEGORIES_LIST_CACHE_KEY = "farms:categories:list"
CATEGORY_CACHE_KEY_PREFIX = "farms:categories:item"


def _cache_get(key):
    try:
        redis_client = get_redis_client()
        payload = redis_client.get(key)
        return json.loads(payload) if payload else None
    except Exception as e:
        logger.warning("Redis unavailable, skipping categories cache read: %s", e)
        return None


def _cache_set(key, value, ttl=120):
    try:
        redis_client = get_redis_client()
        redis_client.setex(key, ttl, json.dumps(value))
    except Exception as e:
        logger.warning("Redis unavailable, skipping categories cache write: %s", e)


def _cache_delete(*keys):
    if not keys:
        return
    try:
        redis_client = get_redis_client()
        redis_client.delete(*keys)
    except Exception as e:
        logger.warning("Redis unavailable, skipping categories cache delete: %s", e)


@categories.route("", methods=["GET"])
@categories.route("/", methods=["GET"])
def get_categories():
    cached = _cache_get(CATEGORIES_LIST_CACHE_KEY)
    if cached is not None:
        return jsonify(envelope(cached, "Categories fetched", 200)), 200

    try:
        conn, cursor = db_connection()
        cursor.execute("SELECT id, name, description FROM Categories ORDER BY name ASC")
        rows = cursor.fetchall()
        conn.close()
        payload = [dict(row) for row in rows]
        _cache_set(CATEGORIES_LIST_CACHE_KEY, payload)
        return jsonify(envelope(payload, "Categories fetched", 200)), 200
    except Exception as e:
        logger.exception("Failed to fetch categories")
        return jsonify(envelope(None, f"Error: {e}", 500, False)), 500


@categories.route("/<int:category_id>", methods=["GET"])
def get_category(category_id):
    cache_key = f"{CATEGORY_CACHE_KEY_PREFIX}:{category_id}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return jsonify(envelope(cached, "Category fetched", 200)), 200

    try:
        conn, cursor = db_connection()
        cursor.execute(
            "SELECT id, name, description FROM Categories WHERE id = ?",
            (category_id,),
        )
        row = cursor.fetchone()
        conn.close()
        if not row:
            return jsonify(envelope(None, "Category not found", 404, False)), 404
        payload = dict(row)
        _cache_set(cache_key, payload)
        return jsonify(envelope(payload, "Category fetched", 200)), 200
    except Exception as e:
        logger.exception("Failed to fetch category %s", category_id)
        return jsonify(envelope(None, f"Error: {e}", 500, False)), 500
