import json
import logging

from flask import Blueprint, jsonify, request

from database import db_connection
from decorators.roles import user_required
from extensions.redis_client import get_redis_client
from routes import response


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


def _cache_set(key, value, ttl=60):
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


@categories.route("/", methods=["GET"])
def get_categories():
    cached = _cache_get(CATEGORIES_LIST_CACHE_KEY)
    if cached is not None:
        logger.info("Categories list served from cache")
        return jsonify(response(cached, "Successfully retrieved categories.", 200)), 200

    try:
        conn, cursor = db_connection()
        cursor.execute("SELECT * FROM Categories")
        rows = cursor.fetchall()
        categories_payload = [dict(row) for row in rows]
        conn.close()

        _cache_set(CATEGORIES_LIST_CACHE_KEY, categories_payload)
        logger.info("Categories list loaded from DB")
        return jsonify(response(categories_payload, "Successfully retrieved categories.", 200)), 200
    except Exception as e:
        logger.exception("Failed to fetch categories")
        return jsonify(response([], f"Error: {e}", 500)), 500


@categories.route("/<int:category_id>", methods=["GET"])
@user_required
def get_category(category_id):
    cache_key = f"{CATEGORY_CACHE_KEY_PREFIX}:{category_id}"
    cached = _cache_get(cache_key)
    if cached is not None:
        logger.info("Category %s served from cache", category_id)
        return jsonify(response(cached, "Successfully retrieved category.", 200)), 200

    try:
        conn, cursor = db_connection()
        cursor.execute("SELECT * FROM Categories WHERE id = ?", (category_id,))
        row = cursor.fetchone()
        conn.close()

        if not row:
            logger.info("Category %s not found", category_id)
            return jsonify(response(None, "Category not found", 404)), 404

        category_payload = dict(row)
        _cache_set(cache_key, category_payload)
        logger.info("Category %s loaded from DB", category_id)
        return jsonify(response(category_payload, "Successfully retrieved category.", 200)), 200
    except Exception as e:
        logger.exception("Failed to fetch category %s", category_id)
        return jsonify(response(None, f"Error: {e}", 500)), 500


@categories.route("/", methods=["POST"])
@user_required
def create_category():
    try:
        data = request.get_json() or {}
        name = data.get("name")
        description = data.get("description", "")

        if not name:
            return jsonify(response(None, "Category name is required", 400)), 400

        conn, cursor = db_connection()
        cursor.execute("INSERT INTO Categories (name, description) VALUES (?, ?)", (name, description))
        conn.commit()
        new_category_id = cursor.lastrowid
        conn.close()

        new_category = {"id": new_category_id, "name": name, "description": description}
        _cache_delete(CATEGORIES_LIST_CACHE_KEY)
        _cache_set(f"{CATEGORY_CACHE_KEY_PREFIX}:{new_category_id}", new_category)
        logger.info("Category %s created", new_category_id)

        return jsonify(response(new_category, "Category created successfully.", 201)), 201
    except Exception as e:
        logger.exception("Failed to create category")
        return jsonify(response(None, f"Error: {e}", 500)), 500


@categories.route("/<int:category_id>", methods=["PUT"])
@user_required
def update_category(category_id):
    try:
        data = request.get_json() or {}
        name = data.get("name")
        description = data.get("description", "")

        if not name:
            return jsonify(response(None, "Category name is required", 400)), 400

        conn, cursor = db_connection()
        cursor.execute(
            "UPDATE Categories SET name = ?, description = ? WHERE id = ?",
            (name, description, category_id),
        )
        conn.commit()
        updated = cursor.rowcount
        conn.close()

        if updated == 0:
            return jsonify(response(None, "Category not found", 404)), 404

        payload = {"id": category_id, "name": name, "description": description}
        _cache_delete(CATEGORIES_LIST_CACHE_KEY, f"{CATEGORY_CACHE_KEY_PREFIX}:{category_id}")
        _cache_set(f"{CATEGORY_CACHE_KEY_PREFIX}:{category_id}", payload)
        logger.info("Category %s updated", category_id)
        return jsonify(response(payload, "Category updated successfully.", 200)), 200
    except Exception as e:
        logger.exception("Failed to update category %s", category_id)
        return jsonify(response(None, f"Error: {e}", 500)), 500


@categories.route("/<int:category_id>", methods=["DELETE"])
@user_required
def delete_category(category_id):
    try:
        conn, cursor = db_connection()
        cursor.execute("DELETE FROM Categories WHERE id = ?", (category_id,))
        conn.commit()
        deleted = cursor.rowcount
        conn.close()

        if deleted == 0:
            return jsonify(response(None, "Category not found", 404)), 404

        _cache_delete(CATEGORIES_LIST_CACHE_KEY, f"{CATEGORY_CACHE_KEY_PREFIX}:{category_id}")
        logger.info("Category %s deleted", category_id)
        return jsonify(response(category_id, "Category deleted successfully.", 200)), 200
    except Exception as e:
        logger.exception("Failed to delete category %s", category_id)
        return jsonify(response(None, f"Error: {e}", 500)), 500
