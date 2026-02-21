import logging

from flask import Blueprint, jsonify, request

from database import db_connection
from decorators.roles import admin_required
from routes.api_envelope import envelope
from routes.farms.categories import (
    CATEGORIES_LIST_CACHE_KEY,
    CATEGORY_CACHE_KEY_PREFIX,
    _cache_delete,
    _cache_set,
)


categories_admin = Blueprint("categories_admin", __name__)
logger = logging.getLogger(__name__)


@categories_admin.route("", methods=["POST"])
@categories_admin.route("/", methods=["POST"])
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


@categories_admin.route("/<int:category_id>", methods=["PUT"])
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


@categories_admin.route("/<int:category_id>", methods=["DELETE"])
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
