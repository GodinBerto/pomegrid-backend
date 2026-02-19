import logging
from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from database import db_connection
from routes import response

jobs = Blueprint("jobs", __name__)
logger = logging.getLogger(__name__)

ALLOWED_JOB_STATUSES = {"pending", "accepted", "in_progress", "completed", "cancelled"}


def _is_admin(user_id):
    conn, cursor = db_connection()
    cursor.execute("SELECT is_admin, user_type FROM Users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return bool(row and (row["is_admin"] or row["user_type"] in {"admin", "super admin"}))


@jobs.route("/hire", methods=["POST"])
@jwt_required()
def hire_artisan():
    user_id = get_jwt_identity()
    data = request.get_json() or {}

    worker_id = data.get("worker_id")
    job_type = data.get("job_type")
    budget = data.get("budget")
    address = data.get("address")
    scheduled_at = data.get("scheduled_at")

    if not worker_id or not job_type:
        return jsonify(response(None, "worker_id and job_type are required", 400)), 400

    try:
        conn, cursor = db_connection()
        cursor.execute("SELECT id, is_available FROM Workers WHERE id = ?", (worker_id,))
        worker = cursor.fetchone()
        if not worker:
            conn.close()
            return jsonify(response(None, "Artisan not found", 404)), 404
        if not worker["is_available"]:
            conn.close()
            return jsonify(response(None, "Artisan is not currently available", 400)), 400

        cursor.execute(
            """
            INSERT INTO Jobs (
                worker_id, user_id, job_type, status, budget, address, scheduled_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (worker_id, user_id, job_type, "pending", budget, address, scheduled_at),
        )
        conn.commit()
        job_id = cursor.lastrowid
        cursor.execute("SELECT * FROM Jobs WHERE id = ?", (job_id,))
        job = cursor.fetchone()
        conn.close()
        return jsonify(response(dict(job), "Artisan hired successfully", 201)), 201
    except Exception as e:
        logger.exception("Failed to hire artisan")
        return jsonify(response(None, f"Error: {e}", 500)), 500


@jobs.route("/my-jobs", methods=["GET"])
@jwt_required()
def get_my_jobs():
    user_id = get_jwt_identity()
    status = (request.args.get("status") or "").strip()

    try:
        conn, cursor = db_connection()
        params = [user_id]
        query = """
            SELECT
                j.*,
                w.name AS worker_name,
                w.profession AS worker_profession,
                w.location AS worker_location
            FROM Jobs j
            JOIN Workers w ON w.id = j.worker_id
            WHERE j.user_id = ?
        """
        if status:
            query += " AND j.status = ?"
            params.append(status)
        query += " ORDER BY j.created_at DESC"
        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()
        conn.close()
        return jsonify(response([dict(row) for row in rows], "Jobs fetched", 200)), 200
    except Exception as e:
        logger.exception("Failed to fetch user jobs")
        return jsonify(response(None, f"Error: {e}", 500)), 500


@jobs.route("/", methods=["GET"])
@jwt_required()
def list_jobs_for_admin():
    user_id = get_jwt_identity()
    if not _is_admin(user_id):
        return jsonify(response(None, "Admin access required", 403)), 403

    status = (request.args.get("status") or "").strip()
    page = request.args.get("page", default=1, type=int)
    size = request.args.get("size", default=20, type=int)
    if page < 1:
        page = 1
    if size < 1:
        size = 20
    offset = (page - 1) * size

    try:
        conn, cursor = db_connection()
        params = []
        count_query = "SELECT COUNT(*) AS total FROM Jobs WHERE 1=1"
        if status:
            count_query += " AND status = ?"
            params.append(status)
        cursor.execute(count_query, tuple(params))
        total = cursor.fetchone()["total"]

        list_query = """
            SELECT
                j.*,
                u.full_name AS user_name,
                u.email AS user_email,
                w.name AS worker_name,
                w.profession AS worker_profession
            FROM Jobs j
            JOIN Users u ON u.id = j.user_id
            JOIN Workers w ON w.id = j.worker_id
            WHERE 1=1
        """
        if status:
            list_query += " AND j.status = ?"
        list_query += " ORDER BY j.created_at DESC LIMIT ? OFFSET ?"

        query_params = list(params)
        query_params.extend([size, offset])
        cursor.execute(list_query, tuple(query_params))
        rows = cursor.fetchall()
        conn.close()

        payload = {
            "jobs": [dict(row) for row in rows],
            "page": page,
            "size": size,
            "total": total,
        }
        return jsonify(response(payload, "Jobs fetched", 200)), 200
    except Exception as e:
        logger.exception("Failed to fetch admin jobs")
        return jsonify(response(None, f"Error: {e}", 500)), 500


@jobs.route("/<int:job_id>/status", methods=["PUT"])
@jwt_required()
def update_job_status(job_id):
    user_id = get_jwt_identity()
    data = request.get_json() or {}
    status = data.get("status")
    if status not in ALLOWED_JOB_STATUSES:
        return jsonify(response(None, "Invalid status", 400)), 400

    try:
        conn, cursor = db_connection()
        cursor.execute("SELECT id, worker_id, user_id, status FROM Jobs WHERE id = ?", (job_id,))
        job = cursor.fetchone()
        if not job:
            conn.close()
            return jsonify(response(None, "Job not found", 404)), 404

        admin = _is_admin(user_id)
        if str(job["user_id"]) != str(user_id) and not admin:
            conn.close()
            return jsonify(response(None, "Not allowed to update this job", 403)), 403

        completion_fragment = ", completed_at = CURRENT_TIMESTAMP" if status == "completed" else ""
        cursor.execute(
            f"""
            UPDATE Jobs
            SET status = ?, updated_at = CURRENT_TIMESTAMP{completion_fragment}
            WHERE id = ?
            """,
            (status, job_id),
        )
        cursor.execute(
            """
            SELECT COUNT(*) AS completed_count
            FROM Jobs
            WHERE worker_id = ? AND status = 'completed'
            """,
            (job["worker_id"],),
        )
        completed_count = cursor.fetchone()["completed_count"]
        cursor.execute(
            """
            UPDATE Workers
            SET completed_jobs = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (completed_count, job["worker_id"]),
        )
        conn.commit()
        cursor.execute("SELECT * FROM Jobs WHERE id = ?", (job_id,))
        updated = cursor.fetchone()
        conn.close()
        return jsonify(response(dict(updated), "Job status updated", 200)), 200
    except Exception as e:
        logger.exception("Failed to update job status")
        return jsonify(response(None, f"Error: {e}", 500)), 500


@jobs.route("/<int:job_id>/rating", methods=["POST"])
@jwt_required()
def rate_job_artisan(job_id):
    user_id = get_jwt_identity()
    data = request.get_json() or {}
    rating = data.get("rating")
    feedback = data.get("feedback")

    if rating is None or not isinstance(rating, int) or rating < 1 or rating > 5:
        return jsonify(response(None, "rating must be an integer between 1 and 5", 400)), 400

    try:
        conn, cursor = db_connection()
        cursor.execute(
            "SELECT id, worker_id, user_id, status FROM Jobs WHERE id = ?",
            (job_id,),
        )
        job = cursor.fetchone()
        if not job:
            conn.close()
            return jsonify(response(None, "Job not found", 404)), 404
        if str(job["user_id"]) != str(user_id):
            conn.close()
            return jsonify(response(None, "You can only rate your own job", 403)), 403
        if job["status"] != "completed":
            conn.close()
            return jsonify(response(None, "Job must be completed before rating", 400)), 400

        cursor.execute(
            "SELECT id FROM Worker_Ratings WHERE job_id = ? AND user_id = ?",
            (job_id, user_id),
        )
        existing = cursor.fetchone()
        if existing:
            conn.close()
            return jsonify(response(None, "Rating already submitted for this job", 409)), 409

        cursor.execute(
            """
            INSERT INTO Worker_Ratings (worker_id, user_id, job_id, feedback, rating)
            VALUES (?, ?, ?, ?, ?)
            """,
            (job["worker_id"], user_id, job_id, feedback, rating),
        )

        cursor.execute(
            "SELECT AVG(rating) AS avg_rating FROM Worker_Ratings WHERE worker_id = ?",
            (job["worker_id"],),
        )
        avg_rating = cursor.fetchone()["avg_rating"]
        cursor.execute(
            "SELECT COUNT(*) AS reviews_count FROM Worker_Ratings WHERE worker_id = ?",
            (job["worker_id"],),
        )
        reviews_count = cursor.fetchone()["reviews_count"]
        cursor.execute(
            """
            UPDATE Workers
            SET ratings = ?, reviews_count = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (round(avg_rating, 2), reviews_count, job["worker_id"]),
        )
        conn.commit()
        conn.close()
        return jsonify(response({"worker_id": job["worker_id"], "rating": rating}, "Rating submitted", 201)), 201
    except Exception as e:
        logger.exception("Failed to submit artisan rating")
        return jsonify(response(None, f"Error: {e}", 500)), 500
