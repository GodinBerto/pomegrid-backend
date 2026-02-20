import json
import logging

from flask import Blueprint, jsonify, request

from database import db_connection
from decorators.roles import admin_required
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


@categories.route("", methods=["POST"])
@categories.route("/", methods=["POST"])
@admin_required
def create_category():
    data = request.get_json() or {}
    name = str(data.get("name") or "").strip()
    description = str(data.get("description") or "").strip()
    if not name:
        return jsonify(envelope(None, "name is required", 400, False)), 400

    try:
        conn, cursor = db_connection()
        cursor.execute(
            "INSERT INTO Categories (name, description) VALUES (?, ?)",
            (name, description),
        )
        category_id = cursor.lastrowid
        conn.commit()
        conn.close()

        payload = {"id": category_id, "name": name, "description": description}
        _cache_delete(CATEGORIES_LIST_CACHE_KEY, f"{CATEGORY_CACHE_KEY_PREFIX}:{category_id}")
        _cache_set(f"{CATEGORY_CACHE_KEY_PREFIX}:{category_id}", payload)
        return jsonify(envelope(payload, "Category created", 201)), 201
    except Exception as e:
        logger.exception("Failed to create category")
        return jsonify(envelope(None, f"Error: {e}", 500, False)), 500


@categories.route("/<int:category_id>", methods=["PUT"])
@admin_required
def update_category(category_id):
    data = request.get_json() or {}
    name = str(data.get("name") or "").strip()
    description = str(data.get("description") or "").strip()
    if not name:
        return jsonify(envelope(None, "name is required", 400, False)), 400

    try:
        conn, cursor = db_connection()
        cursor.execute(
            "UPDATE Categories SET name = ?, description = ? WHERE id = ?",
            (name, description, category_id),
        )
        conn.commit()
        if cursor.rowcount == 0:
            conn.close()
            return jsonify(envelope(None, "Category not found", 404, False)), 404
        conn.close()

        payload = {"id": category_id, "name": name, "description": description}
        _cache_delete(CATEGORIES_LIST_CACHE_KEY, f"{CATEGORY_CACHE_KEY_PREFIX}:{category_id}")
        _cache_set(f"{CATEGORY_CACHE_KEY_PREFIX}:{category_id}", payload)
        return jsonify(envelope(payload, "Category updated", 200)), 200
    except Exception as e:
        logger.exception("Failed to update category %s", category_id)
        return jsonify(envelope(None, f"Error: {e}", 500, False)), 500


@categories.route("/<int:category_id>", methods=["DELETE"])
@admin_required
def delete_category(category_id):
    try:
        conn, cursor = db_connection()
        cursor.execute("DELETE FROM Categories WHERE id = ?", (category_id,))
        conn.commit()
        if cursor.rowcount == 0:
            conn.close()
            return jsonify(envelope(None, "Category not found", 404, False)), 404
        conn.close()

        _cache_delete(CATEGORIES_LIST_CACHE_KEY, f"{CATEGORY_CACHE_KEY_PREFIX}:{category_id}")
        return jsonify(envelope({"id": category_id}, "Category deleted", 200)), 200
    except Exception as e:
        logger.exception("Failed to delete category %s", category_id)
        return jsonify(envelope(None, f"Error: {e}", 500, False)), 500
