import json
from flask import Blueprint, jsonify, request
from database import db_connection
from extensions.redis_client import get_redis_client
from routes import response

workers = Blueprint("workers", __name__)


@workers.route("/", methods=["GET"])
def GetWorkers():
    cache_key = "workers:all"
    cache_ttl_seconds = 60

    try:
        redis_client = get_redis_client()
        cached = redis_client.get(cache_key)
        if cached:
            workers_list = json.loads(cached)
            return jsonify(response(workers_list, "Workers Fetched", 200)), 200
    except Exception as e:
        print("Redis unavailable, skipping workers cache read:", e)

    try:
        conn, cursor = db_connection()
        cursor.execute("SELECT * FROM Workers")
        rows = cursor.fetchall()
        workers_list = [dict(row) for row in rows]
        conn.close()

        try:
            redis_client = get_redis_client()
            redis_client.setex(cache_key, cache_ttl_seconds, json.dumps(workers_list))
        except Exception as e:
            print("Redis unavailable, skipping workers cache write:", e)

        return jsonify(response(workers_list, "Workers Fetched", 200)), 200
    except Exception as e:
        return jsonify(response([], f"Error: {e}", 500)), 500


@workers.route("/<int:worker_id>", methods=["GET"])
def GetWorker(worker_id):
    cache_key = f"workers:{worker_id}"
    cache_ttl_seconds = 60

    try:
        redis_client = get_redis_client()
        cached = redis_client.get(cache_key)
        if cached:
            worker = json.loads(cached)
            return jsonify(response(worker, "Worker Fetched", 200)), 200
    except Exception as e:
        print("Redis unavailable, skipping worker cache read:", e)

    try:
        conn, cursor = db_connection()
        cursor.execute("SELECT * FROM Workers WHERE id = ?", (worker_id,))
        row = cursor.fetchone()
        conn.close()

        if not row:
            return jsonify(response(None, "Worker not found", 404)), 404

        worker = dict(row)

        try:
            redis_client = get_redis_client()
            redis_client.setex(cache_key, cache_ttl_seconds, json.dumps(worker))
        except Exception as e:
            print("Redis unavailable, skipping worker cache write:", e)

        return jsonify(response(worker, "Worker Fetched", 200)), 200
    except Exception as e:
        return jsonify(response(None, f"Error: {e}", 500)), 500


@workers.route("/", methods=["POST"])
def CreateWorker():
    data = request.get_json() or {}

    name = data.get("name")
    phone_number = data.get("phone_number")
    profession = data.get("profession")
    location = data.get("location")

    if not all([name, phone_number, profession, location]):
        return jsonify(response(None, "Missing required fields", 400)), 400

    email = data.get("email")
    phone_number_2 = data.get("phone_number_2")
    bio = data.get("bio")
    is_varified = data.get("is_varified")
    ratings = data.get("ratings")
    image = data.get("image")
    is_available = data.get("is_available")

    try:
        conn, cursor = db_connection()
        cursor.execute(
            """
            INSERT INTO Workers (
                name, phone_number, email, phone_number_2, bio,
                profession, is_varified, location, ratings, image, is_available
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                phone_number,
                email,
                phone_number_2,
                bio,
                profession,
                is_varified,
                location,
                ratings,
                image,
                is_available,
            ),
        )
        conn.commit()
        worker_id = cursor.lastrowid
        conn.close()

        worker = {
            "id": worker_id,
            "name": name,
            "phone_number": phone_number,
            "email": email,
            "phone_number_2": phone_number_2,
            "bio": bio,
            "profession": profession,
            "is_varified": is_varified,
            "location": location,
            "ratings": ratings,
            "image": image,
            "is_available": is_available,
        }

        try:
            redis_client = get_redis_client()
            redis_client.delete("workers:all")
            redis_client.setex(f"workers:{worker_id}", 60, json.dumps(worker))
        except Exception as e:
            print("Redis unavailable, skipping workers cache write:", e)

        return jsonify(response(worker, "Worker created successfully.", 201)), 201
    except Exception as e:
        return jsonify(response(None, f"Error: {e}", 500)), 500


@workers.route("/<int:worker_id>", methods=["PUT"])
def UpdateWorker(worker_id):
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
        "image",
        "is_available",
    ]

    updates = {k: data.get(k) for k in allowed_fields if k in data}
    if not updates:
        return jsonify(response(None, "No fields provided for update", 400)), 400

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
            return jsonify(response(None, "Worker not found", 404)), 404

        cursor.execute("SELECT * FROM Workers WHERE id = ?", (worker_id,))
        row = cursor.fetchone()
        conn.close()

        worker = dict(row) if row else {"id": worker_id, **updates}

        try:
            redis_client = get_redis_client()
            redis_client.delete("workers:all")
            redis_client.setex(f"workers:{worker_id}", 60, json.dumps(worker))
        except Exception as e:
            print("Redis unavailable, skipping workers cache write:", e)

        return jsonify(response(worker, "Worker updated successfully.", 200)), 200
    except Exception as e:
        return jsonify(response(None, f"Error: {e}", 500)), 500


@workers.route("/<int:worker_id>", methods=["DELETE"])
def DeleteWorker(worker_id):
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
            redis_client.delete("workers:all")
            redis_client.delete(f"workers:{worker_id}")
        except Exception as e:
            print("Redis unavailable, skipping workers cache delete:", e)

        return jsonify(response(worker_id, "Worker deleted successfully.", 200)), 200
    except Exception as e:
        return jsonify(response(None, f"Error: {e}", 500)), 500
