import logging

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity

from database import db_connection
from decorators.roles import admin_required
from routes import response
from routes.artisans.workers import clear_workers_list_cache


admins = Blueprint("admins", __name__)
logger = logging.getLogger(__name__)


@admins.route("/promote-user/<int:user_id>", methods=["POST"])
@admin_required
def promote_user_to_admin(user_id):
    try:
        conn, cursor = db_connection()
        cursor.execute("SELECT id FROM Users WHERE id = ?", (user_id,))
        user = cursor.fetchone()
        if not user:
            conn.close()
            return jsonify(response(None, "User not found", 404)), 404

        cursor.execute(
            """
            UPDATE Users
            SET
                is_admin = 1,
                user_type = CASE
                    WHEN LOWER(TRIM(user_type)) = 'super admin' THEN 'super admin'
                    ELSE 'admin'
                END
            WHERE id = ?
            """,
            (user_id,),
        )
        cursor.execute(
            "INSERT OR IGNORE INTO Admins (user_id) VALUES (?)",
            (user_id,),
        )
        conn.commit()
        conn.close()
        return jsonify(response({"user_id": user_id}, "User promoted to admin", 200)), 200
    except Exception as e:
        logger.exception("Failed to promote user to admin")
        return jsonify(response(None, f"Error: {e}", 500)), 500


@admins.route("/artisans", methods=["POST"])
@admin_required
def create_artisan():
    data = request.get_json() or {}
    required_fields = ["name", "phone_number", "profession", "location"]
    if not all(data.get(field) for field in required_fields):
        return jsonify(response(None, "Missing required fields", 400)), 400

    admin_id = get_jwt_identity()
    payload = (
        data.get("name"),
        data.get("phone_number"),
        data.get("email"),
        data.get("phone_number_2"),
        data.get("bio"),
        data.get("profession"),
        data.get("is_varified", 0),
        data.get("location"),
        data.get("ratings", 0),
        data.get("reviews_count", 0),
        data.get("image"),
        data.get("is_available", 1),
        data.get("hourly_rate", 0),
        data.get("years_experience", 0),
        data.get("completed_jobs", 0),
        admin_id,
        admin_id,
    )

    try:
        conn, cursor = db_connection()
        cursor.execute(
            """
            INSERT INTO Workers (
                name, phone_number, email, phone_number_2, bio,
                profession, is_varified, location, ratings, reviews_count, image, is_available,
                hourly_rate, years_experience, completed_jobs,
                created_by_admin_id, updated_by_admin_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            payload,
        )
        conn.commit()
        worker_id = cursor.lastrowid
        conn.close()
        clear_workers_list_cache()
        return jsonify(response({"worker_id": worker_id}, "Artisan created", 201)), 201
    except Exception as e:
        logger.exception("Failed to create artisan by admin")
        return jsonify(response(None, f"Error: {e}", 500)), 500


@admins.route("/artisans/<int:worker_id>", methods=["PUT"])
@admin_required
def update_artisan(worker_id):
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
    updates = {k: data[k] for k in allowed_fields if k in data}
    if not updates:
        return jsonify(response(None, "No fields provided for update", 400)), 400

    updates["updated_by_admin_id"] = get_jwt_identity()
    set_clause = ", ".join([f"{k} = ?" for k in updates.keys()])
    values = list(updates.values())
    values.append(worker_id)

    try:
        conn, cursor = db_connection()
        cursor.execute(
            f"UPDATE Workers SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            values,
        )
        conn.commit()
        if cursor.rowcount == 0:
            conn.close()
            return jsonify(response(None, "Artisan not found", 404)), 404

        cursor.execute("SELECT * FROM Workers WHERE id = ?", (worker_id,))
        worker = cursor.fetchone()
        conn.close()
        clear_workers_list_cache()
        return jsonify(response(dict(worker), "Artisan updated", 200)), 200
    except Exception as e:
        logger.exception("Failed to update artisan by admin")
        return jsonify(response(None, f"Error: {e}", 500)), 500


@admins.route("/artisans/<int:worker_id>", methods=["DELETE"])
@admin_required
def delete_artisan(worker_id):
    try:
        conn, cursor = db_connection()
        cursor.execute("DELETE FROM Workers WHERE id = ?", (worker_id,))
        conn.commit()
        if cursor.rowcount == 0:
            conn.close()
            return jsonify(response(None, "Artisan not found", 404)), 404
        conn.close()
        clear_workers_list_cache()
        return jsonify(response({"worker_id": worker_id}, "Artisan deleted", 200)), 200
    except Exception as e:
        logger.exception("Failed to delete artisan by admin")
        return jsonify(response(None, f"Error: {e}", 500)), 500
