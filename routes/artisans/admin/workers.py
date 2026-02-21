import json
import logging

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity

from database import db_connection
from decorators.roles import admin_required
from extensions.redis_client import get_redis_client
from routes import response
from routes.artisans.workers import (
    API_WORKER_COLUMNS,
    _canonical_profession,
    _normalize_worker,
    clear_workers_list_cache,
)


workers_admin = Blueprint("workers_admin", __name__)
logger = logging.getLogger(__name__)


@workers_admin.route("/", methods=["POST"])
@admin_required
def create_worker():
    data = request.get_json() or {}

    name = data.get("name")
    phone_number = data.get("phone_number")
    location = data.get("location")
    profession = _canonical_profession(data.get("profession"))

    if not all([name, phone_number, location, profession]):
        return jsonify(response(None, "Missing required fields", 400)), 400

    email = data.get("email")
    phone_number_2 = data.get("phone_number_2")
    bio = data.get("bio")
    image = data.get("image")
    ratings = data.get("ratings", 0)
    is_available = data.get("is_available", 1)
    is_varified = data.get("is_varified", 0)
    reviews_count = data.get("reviews_count", 0)
    hourly_rate = data.get("hourly_rate", 0)
    years_experience = data.get("years_experience", 0)
    completed_jobs = data.get("completed_jobs", 0)
    admin_id = get_jwt_identity()

    try:
        conn, cursor = db_connection()
        cursor.execute(
            """
            INSERT INTO Workers (
                name, phone_number, email, phone_number_2, profession, bio, image,
                location, ratings, reviews_count, is_available, is_varified,
                hourly_rate, years_experience, completed_jobs
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                phone_number,
                email,
                phone_number_2,
                profession,
                bio,
                image,
                location,
                ratings,
                reviews_count,
                is_available,
                is_varified,
                hourly_rate,
                years_experience,
                completed_jobs,
            ),
        )
        worker_id = cursor.lastrowid
        cursor.execute(
            """
            UPDATE Workers
            SET created_by_admin_id = ?, updated_by_admin_id = ?
            WHERE id = ?
            """,
            (admin_id, admin_id, worker_id),
        )
        conn.commit()
        cursor.execute(
            f"SELECT {API_WORKER_COLUMNS} FROM Workers WHERE id = ?",
            (worker_id,),
        )
        row = cursor.fetchone()
        conn.close()
        worker = _normalize_worker(row)

        try:
            redis_client = get_redis_client()
            clear_workers_list_cache()
            redis_client.setex(f"workers:{worker_id}", 60, json.dumps(worker))
        except Exception as e:
            logger.warning("Redis unavailable, skipping workers cache write: %s", e)

        return jsonify(response(worker, "Worker created successfully.", 201)), 201
    except Exception as e:
        return jsonify(response(None, f"Error: {e}", 500)), 500


@workers_admin.route("/<int:worker_id>", methods=["PUT"])
@admin_required
def update_worker(worker_id):
    data = request.get_json() or {}

    allowed_fields = [
        "name",
        "phone_number",
        "email",
        "phone_number_2",
        "bio",
        "profession",
        "is_varified",
        "location",
        "ratings",
        "reviews_count",
        "image",
        "is_available",
        "hourly_rate",
        "years_experience",
        "completed_jobs",
    ]

    updates = {k: data.get(k) for k in allowed_fields if k in data}
    if not updates:
        return jsonify(response(None, "No fields provided for update", 400)), 400

    if "profession" in updates:
        profession = _canonical_profession(updates["profession"])
        if not profession:
            return jsonify(response(None, "Invalid profession", 400)), 400
        updates["profession"] = profession

    set_clause = ", ".join([f"{k} = ?" for k in updates.keys()])
    values = list(updates.values())
    values.append(get_jwt_identity())
    values.append(worker_id)

    try:
        conn, cursor = db_connection()
        cursor.execute(
            f"""
            UPDATE Workers
            SET {set_clause}, updated_by_admin_id = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            values,
        )
        conn.commit()

        if cursor.rowcount == 0:
            conn.close()
            return jsonify(response(None, "Worker not found", 404)), 404

        cursor.execute(
            f"SELECT {API_WORKER_COLUMNS} FROM Workers WHERE id = ?",
            (worker_id,),
        )
        row = cursor.fetchone()
        conn.close()
        worker = _normalize_worker(row)

        try:
            redis_client = get_redis_client()
            clear_workers_list_cache()
            redis_client.setex(f"workers:{worker_id}", 60, json.dumps(worker))
        except Exception as e:
            logger.warning("Redis unavailable, skipping workers cache write: %s", e)

        return jsonify(response(worker, "Worker updated successfully.", 200)), 200
    except Exception as e:
        return jsonify(response(None, f"Error: {e}", 500)), 500


@workers_admin.route("/<int:worker_id>", methods=["DELETE"])
@admin_required
def delete_worker(worker_id):
    try:
        conn, cursor = db_connection()
        cursor.execute("DELETE FROM Workers WHERE id = ?", (worker_id,))
        conn.commit()

        if cursor.rowcount == 0:
            conn.close()
            return jsonify(response(None, "Worker not found", 404)), 404

        conn.close()

        try:
            redis_client = get_redis_client()
            clear_workers_list_cache()
            redis_client.delete(f"workers:{worker_id}")
        except Exception as e:
            logger.warning("Redis unavailable, skipping workers cache delete: %s", e)

        return jsonify(response(worker_id, "Worker deleted successfully.", 200)), 200
    except Exception as e:
        return jsonify(response(None, f"Error: {e}", 500)), 500
