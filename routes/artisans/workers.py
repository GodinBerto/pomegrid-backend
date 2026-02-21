import json
import logging

from flask import Blueprint, jsonify, request

from database import db_connection
from extensions.redis_client import get_redis_client
from routes import response

workers = Blueprint("workers", __name__)
logger = logging.getLogger(__name__)

ALLOWED_PROFESSIONS = {
    "Electrician",
    "Plumber",
    "Mason",
    "Carpenter",
    "Mechanic",
}

API_WORKER_COLUMNS = """
    id,
    name,
    email,
    CAST(phone_number AS TEXT) AS phone_number,
    CAST(phone_number_2 AS TEXT) AS phone_number_2,
    profession,
    bio,
    image,
    location,
    CAST(COALESCE(ratings, 0) AS REAL) AS ratings,
    COALESCE(is_available, 1) AS is_available,
    COALESCE(is_varified, 0) AS is_varified,
    created_at,
    updated_at,
    COALESCE(hourly_rate, 0) AS hourly_rate,
    COALESCE(years_experience, 0) AS years_experience,
    COALESCE(completed_jobs, 0) AS completed_jobs,
    COALESCE(reviews_count, 0) AS reviews_count
"""


def _api_response(data, message, http_status=200, status=True):
    return jsonify({"status": status, "message": message, "data": data}), http_status


def _canonical_profession(value):
    if not value:
        return None
    normalized = str(value).strip().lower()
    for profession in ALLOWED_PROFESSIONS:
        if profession.lower() == normalized:
            return profession
    return None


def _parse_bool_query(value):
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized == "":
        return None
    if normalized in {"1", "true", "yes"}:
        return True
    if normalized in {"0", "false", "no"}:
        return False
    return "invalid"


def _normalize_worker(row):
    worker = dict(row)
    worker["is_available"] = bool(worker.get("is_available"))
    worker["is_varified"] = bool(worker.get("is_varified"))
    worker["ratings"] = float(worker.get("ratings") or 0)
    worker["reviews_count"] = int(worker.get("reviews_count") or 0)
    worker["hourly_rate"] = int(worker.get("hourly_rate") or 0)
    worker["years_experience"] = int(worker.get("years_experience") or 0)
    worker["completed_jobs"] = int(worker.get("completed_jobs") or 0)
    if worker.get("phone_number") is not None:
        worker["phone_number"] = str(worker["phone_number"])
    if worker.get("phone_number_2") is not None:
        worker["phone_number_2"] = str(worker["phone_number_2"])
    return worker


def clear_workers_list_cache():
    try:
        redis_client = get_redis_client()
        list_keys = redis_client.keys("workers:list:*")
        if list_keys:
            redis_client.delete(*list_keys)
        redis_client.delete("workers:all")
    except Exception as e:
        logger.warning("Redis unavailable, skipping workers cache clear: %s", e)


@workers.route("/", methods=["GET"])
def GetWorkers():
    location = (request.args.get("location") or "").strip()
    worker_type_raw = (request.args.get("type") or "").strip()
    available_raw = request.args.get("available")
    min_rating_raw = (request.args.get("min_rating") or "").strip()
    page = request.args.get("page", default=1, type=int) or 1
    size = request.args.get("size", default=10, type=int) or 10

    if page < 1:
        page = 1
    if size < 1:
        size = 10

    worker_type = None
    if worker_type_raw:
        worker_type = _canonical_profession(worker_type_raw)
        if not worker_type:
            return _api_response(
                None,
                "type must be one of: Electrician, Plumber, Mason, Carpenter, Mechanic",
                400,
                False,
            )

    available = _parse_bool_query(available_raw)
    if available == "invalid":
        return _api_response(None, "available must be true or false", 400, False)

    min_rating = None
    if min_rating_raw:
        try:
            min_rating = float(min_rating_raw)
        except ValueError:
            return _api_response(None, "min_rating must be a number", 400, False)
        if min_rating < 0:
            min_rating = 0

    offset = (page - 1) * size
    cache_key = (
        f"workers:list:location={location or 'all'}:"
        f"type={worker_type or 'all'}:available={available}:"
        f"min_rating={min_rating if min_rating is not None else 'all'}:"
        f"page={page}:size={size}"
    )
    cache_ttl_seconds = 60

    try:
        redis_client = get_redis_client()
        cached = redis_client.get(cache_key)
        if cached:
            return _api_response(json.loads(cached), "Workers fetched", 200, True)
    except Exception as e:
        logger.warning("Redis unavailable, skipping workers cache read: %s", e)

    try:
        conn, cursor = db_connection()
        where_clauses = []
        params = []

        if location:
            where_clauses.append("LOWER(location) = LOWER(?)")
            params.append(location)
        if worker_type:
            where_clauses.append("LOWER(profession) = LOWER(?)")
            params.append(worker_type)
        if available is not None:
            where_clauses.append("COALESCE(is_available, 0) = ?")
            params.append(1 if available else 0)
        if min_rating is not None:
            where_clauses.append("COALESCE(ratings, 0) >= ?")
            params.append(min_rating)

        where_sql = ""
        if where_clauses:
            where_sql = f" WHERE {' AND '.join(where_clauses)}"

        cursor.execute(f"SELECT COUNT(*) as total FROM Workers{where_sql}", tuple(params))
        total = cursor.fetchone()["total"]

        list_params = list(params)
        list_params.extend([size, offset])
        cursor.execute(
            f"""
            SELECT {API_WORKER_COLUMNS}
            FROM Workers
            {where_sql}
            ORDER BY COALESCE(ratings, 0) DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            tuple(list_params),
        )
        rows = cursor.fetchall()
        conn.close()

        payload = {
            "workers": [_normalize_worker(row) for row in rows],
            "location": location or None,
            "page": page,
            "size": size,
            "total": total,
        }

        try:
            redis_client = get_redis_client()
            redis_client.setex(cache_key, cache_ttl_seconds, json.dumps(payload))
        except Exception as e:
            logger.warning("Redis unavailable, skipping workers cache write: %s", e)

        return _api_response(payload, "Workers fetched", 200, True)
    except Exception as e:
        return _api_response(None, f"Error: {e}", 500, False)


@workers.route("/<int:worker_id>", methods=["GET"])
def GetWorker(worker_id):
    cache_key = f"workers:{worker_id}"
    cache_ttl_seconds = 60

    try:
        redis_client = get_redis_client()
        cached = redis_client.get(cache_key)
        if cached:
            return _api_response(json.loads(cached), "Worker fetched", 200, True)
    except Exception as e:
        logger.warning("Redis unavailable, skipping worker cache read: %s", e)

    try:
        conn, cursor = db_connection()
        cursor.execute(
            f"SELECT {API_WORKER_COLUMNS} FROM Workers WHERE id = ?",
            (worker_id,),
        )
        row = cursor.fetchone()
        conn.close()

        if not row:
            return _api_response(None, "Worker not found", 404, False)

        worker = _normalize_worker(row)

        try:
            redis_client = get_redis_client()
            redis_client.setex(cache_key, cache_ttl_seconds, json.dumps(worker))
        except Exception as e:
            logger.warning("Redis unavailable, skipping worker cache write: %s", e)

        return _api_response(worker, "Worker fetched", 200, True)
    except Exception as e:
        return _api_response(None, f"Error: {e}", 500, False)


@workers.route("/<int:worker_id>/services", methods=["GET"])
def GetWorkerServices(worker_id):
    try:
        conn, cursor = db_connection()
        cursor.execute("SELECT id FROM Workers WHERE id = ?", (worker_id,))
        worker = cursor.fetchone()
        if not worker:
            conn.close()
            return _api_response(None, "Worker not found", 404, False)

        cursor.execute(
            """
            SELECT
                id,
                worker_id,
                service_code,
                service_name,
                description,
                base_price,
                COALESCE(is_active, 1) AS is_active,
                created_at,
                updated_at
            FROM worker_services
            WHERE worker_id = ? AND COALESCE(is_active, 1) = 1
            ORDER BY created_at DESC
            """,
            (worker_id,),
        )
        rows = cursor.fetchall()
        conn.close()

        services = []
        for row in rows:
            service = dict(row)
            service["is_active"] = bool(service.get("is_active"))
            services.append(service)

        return _api_response(services, "Worker services fetched", 200, True)
    except Exception as e:
        logger.exception("Failed to fetch worker services")
        return _api_response(None, f"Error: {e}", 500, False)


@workers.route("/<int:worker_id>/ratings", methods=["GET"])
def GetWorkerRatings(worker_id):
    try:
        conn, cursor = db_connection()
        cursor.execute(
            """
            SELECT
                wr.id,
                wr.job_id,
                wr.feedback,
                wr.rating,
                wr.created_at,
                u.full_name AS user_name
            FROM Worker_Ratings wr
            JOIN Users u ON u.id = wr.user_id
            WHERE wr.worker_id = ?
            ORDER BY wr.created_at DESC
            """,
            (worker_id,),
        )
        rows = cursor.fetchall()
        conn.close()
        return jsonify(response([dict(row) for row in rows], "Worker ratings fetched", 200)), 200
    except Exception as e:
        logger.exception("Failed to fetch worker ratings")
        return jsonify(response(None, f"Error: {e}", 500)), 500
