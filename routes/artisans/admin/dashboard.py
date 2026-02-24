import json
import logging
import uuid

from flask import Blueprint, g, jsonify, request
from werkzeug.security import generate_password_hash

from database import db_connection
from decorators.rate_limit import rate_limit
from decorators.roles import admin_required
from extensions.redis_client import get_redis_client
from routes.api_envelope import build_meta, envelope, parse_pagination
from routes import response


admin_api = Blueprint("admin_api", __name__)
logger = logging.getLogger(__name__)

ADMIN_CACHE_KEY = "admin:dashboard:summary"
JOB_STATUSES = {"pending", "confirmed", "in_progress", "completed", "rejected", "cancelled", "accepted"}


def _admin_id():
    return int(g.current_user["id"])


def _cache_get(key):
    try:
        redis_client = get_redis_client()
        value = redis_client.get(key)
        return json.loads(value) if value else None
    except Exception:
        return None


def _cache_set(key, payload, ttl=60):
    try:
        redis_client = get_redis_client()
        redis_client.setex(key, ttl, json.dumps(payload))
    except Exception:
        pass


def _invalidate_cache(pattern="admin:*"):
    try:
        redis_client = get_redis_client()
        keys = redis_client.keys(pattern)
        if keys:
            redis_client.delete(*keys)
    except Exception:
        pass


def _invalidate_worker_dashboard_cache(user_id=None):
    try:
        redis_client = get_redis_client()
        pattern = f"worker:dashboard:summary:{int(user_id)}" if user_id is not None else "worker:dashboard:summary:*"
        keys = redis_client.keys(pattern)
        if keys:
            redis_client.delete(*keys)
    except Exception:
        pass


def _invalidate_workers_public_cache():
    try:
        from routes.artisans.workers import clear_workers_list_cache

        clear_workers_list_cache()
    except Exception:
        pass


def _ensure_wallet(cursor, user_id):
    cursor.execute("SELECT id FROM wallets WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if row:
        return row["id"]
    cursor.execute("INSERT INTO wallets (user_id, balance, pending_balance) VALUES (?, 0, 0)", (user_id,))
    return cursor.lastrowid


def _ensure_conversation(cursor, conv_type, user_a, user_b):
    cursor.execute(
        """
        SELECT c.id
        FROM conversations c
        JOIN conversation_participants cp1 ON cp1.conversation_id = c.id AND cp1.user_id = ?
        JOIN conversation_participants cp2 ON cp2.conversation_id = c.id AND cp2.user_id = ?
        WHERE c.type = ?
        LIMIT 1
        """,
        (user_a, user_b, conv_type),
    )
    row = cursor.fetchone()
    if row:
        return row["id"]

    cursor.execute("INSERT INTO conversations (type) VALUES (?)", (conv_type,))
    conversation_id = cursor.lastrowid
    cursor.execute(
        "INSERT OR IGNORE INTO conversation_participants (conversation_id, user_id) VALUES (?, ?)",
        (conversation_id, user_a),
    )
    cursor.execute(
        "INSERT OR IGNORE INTO conversation_participants (conversation_id, user_id) VALUES (?, ?)",
        (conversation_id, user_b),
    )
    return conversation_id


def _conversation_list(cursor, user_id, conv_type=None):
    where = "cp.user_id = ?"
    params = [user_id]
    if conv_type:
        where += " AND c.type = ?"
        params.append(conv_type)
    cursor.execute(
        f"""
        SELECT
            c.id,
            c.type,
            c.created_at,
            MAX(m.created_at) AS last_message_at,
            (
                SELECT lm.body FROM messages lm
                WHERE lm.conversation_id = c.id
                ORDER BY lm.created_at DESC, lm.id DESC LIMIT 1
            ) AS last_message
        FROM conversations c
        JOIN conversation_participants cp ON cp.conversation_id = c.id
        LEFT JOIN messages m ON m.conversation_id = c.id
        WHERE {where}
        GROUP BY c.id
        ORDER BY COALESCE(MAX(m.created_at), c.created_at) DESC
        """,
        tuple(params),
    )
    return [dict(row) for row in cursor.fetchall()]


def _notify(cursor, user_id, notification_type, title, message, payload=None):
    cursor.execute(
        """
        INSERT INTO notifications (user_id, type, title, message, is_read, payload_json)
        VALUES (?, ?, ?, ?, 0, ?)
        """,
        (user_id, notification_type, title, message, json.dumps(payload or {})),
    )


@admin_api.route("/dashboard/summary", methods=["GET"])
@admin_required
def dashboard_summary():
    cached = _cache_get(ADMIN_CACHE_KEY)
    if cached:
        return jsonify(response(cached, "Dashboard summary", 200)), 200

    conn, cursor = db_connection()
    cursor.execute("SELECT COUNT(*) AS c FROM Users")
    total_users = cursor.fetchone()["c"]
    cursor.execute("SELECT COUNT(*) AS c FROM Users WHERE LOWER(user_type) = 'worker'")
    total_workers = cursor.fetchone()["c"]
    cursor.execute("SELECT COUNT(*) AS c FROM bookings")
    total_jobs = cursor.fetchone()["c"]
    cursor.execute("SELECT COUNT(*) AS c FROM bookings WHERE status = 'pending'")
    pending_jobs = cursor.fetchone()["c"]
    cursor.execute("SELECT COUNT(*) AS c FROM withdrawal_requests WHERE status = 'pending'")
    pending_withdrawals = cursor.fetchone()["c"]
    conn.close()

    payload = {
        "total_users": total_users,
        "total_workers": total_workers,
        "total_jobs": total_jobs,
        "pending_jobs": pending_jobs,
        "pending_withdrawals": pending_withdrawals,
    }
    _cache_set(ADMIN_CACHE_KEY, payload)
    return jsonify(response(payload, "Dashboard summary", 200)), 200


@admin_api.route("/workers", methods=["GET"])
@admin_required
def admin_workers_list():
    page = request.args.get("page", default=1, type=int) or 1
    size = request.args.get("size", default=20, type=int) or 20
    if page < 1:
        page = 1
    if size < 1:
        size = 20
    offset = (page - 1) * size

    conn, cursor = db_connection()
    cursor.execute("SELECT COUNT(*) AS total FROM Users WHERE LOWER(user_type) = 'worker'")
    total = cursor.fetchone()["total"]
    cursor.execute(
        """
        SELECT
            u.id, u.email, u.full_name, u.phone, u.user_type, u.is_active, u.is_admin,
            wp.profession, wp.bio, wp.location, wp.hourly_rate, wp.is_available, wp.verified
        FROM Users u
        LEFT JOIN worker_profiles wp ON wp.user_id = u.id
        WHERE LOWER(u.user_type) = 'worker'
        ORDER BY u.created_at DESC
        LIMIT ? OFFSET ?
        """,
        (size, offset),
    )
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify(response({"workers": rows, "page": page, "size": size, "total": total}, "Workers fetched", 200)), 200


@admin_api.route("/workers", methods=["POST"])
@admin_required
def admin_create_worker():
    data = request.get_json() or {}
    email = (data.get("email") or "").strip().lower()
    full_name = (data.get("full_name") or data.get("name") or "").strip()
    profession = (data.get("profession") or "").strip()
    if not email or not full_name or not profession:
        return jsonify(response(None, "email, full_name and profession are required", 400)), 400

    username = (data.get("username") or email.split("@")[0]).strip() or f"worker_{uuid.uuid4().hex[:6]}"
    password = data.get("password") or "ChangeMe123!"

    conn, cursor = db_connection()
    cursor.execute("SELECT id FROM Users WHERE email = ?", (email,))
    if cursor.fetchone():
        conn.close()
        return jsonify(response(None, "Email already exists", 409)), 409

    cursor.execute("SELECT id FROM Users WHERE username = ?", (username,))
    if cursor.fetchone():
        username = f"{username}_{uuid.uuid4().hex[:6]}"

    cursor.execute(
        """
        INSERT INTO Users (
            username, email, password_hash, full_name, phone, user_type, is_admin, is_active,
            address, date_of_birth, avatar, profile_image_url
        ) VALUES (?, ?, ?, ?, ?, 'worker', 0, 1, ?, ?, ?, ?)
        """,
        (
            username,
            email,
            generate_password_hash(password),
            full_name,
            data.get("phone") or data.get("phone_number"),
            data.get("address"),
            data.get("date_of_birth"),
            data.get("avatar") or data.get("image"),
            data.get("avatar") or data.get("image"),
        ),
    )
    user_id = cursor.lastrowid
    cursor.execute(
        """
        INSERT INTO worker_profiles (
            user_id, profession, bio, location, hourly_rate, is_available, ratings, reviews_count, verified
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            profession,
            data.get("bio"),
            data.get("location"),
            data.get("hourly_rate", 0),
            1 if data.get("is_available", True) else 0,
            data.get("ratings", 0),
            data.get("reviews_count", 0),
            1 if data.get("verified", data.get("is_varified", False)) else 0,
        ),
    )
    _ensure_wallet(cursor, user_id)
    conn.commit()
    conn.close()
    _invalidate_cache()
    _invalidate_workers_public_cache()
    _invalidate_worker_dashboard_cache(user_id)
    return jsonify(response({"user_id": user_id}, "Worker created", 201)), 201

@admin_api.route("/workers/<int:user_id>", methods=["GET"])
@admin_required
def admin_get_worker(user_id):
    conn, cursor = db_connection()
    cursor.execute(
        """
        SELECT
            u.id, u.email, u.full_name, u.phone, u.user_type, u.is_active, u.is_admin,
            u.address, u.avatar, u.date_of_birth,
            wp.profession, wp.bio, wp.location, wp.hourly_rate, wp.is_available, wp.verified
        FROM Users u
        LEFT JOIN worker_profiles wp ON wp.user_id = u.id
        WHERE u.id = ? AND LOWER(u.user_type) = 'worker'
        """,
        (user_id,),
    )
    row = cursor.fetchone()
    conn.close()
    if not row:
        return jsonify(response(None, "Worker not found", 404)), 404
    return jsonify(response(dict(row), "Worker fetched", 200)), 200


@admin_api.route("/workers/<int:user_id>", methods=["PATCH"])
@admin_required
def admin_patch_worker(user_id):
    data = request.get_json() or {}
    user_allowed = ["full_name", "phone", "address", "avatar", "is_active"]
    profile_allowed = ["profession", "bio", "location", "hourly_rate", "is_available", "verified", "ratings", "reviews_count"]
    user_updates = {k: data[k] for k in user_allowed if k in data}
    profile_updates = {k: data[k] for k in profile_allowed if k in data}
    if not user_updates and not profile_updates:
        return jsonify(response(None, "No fields provided for update", 400)), 400

    conn, cursor = db_connection()
    cursor.execute("SELECT id FROM Users WHERE id = ? AND LOWER(user_type) = 'worker'", (user_id,))
    if not cursor.fetchone():
        conn.close()
        return jsonify(response(None, "Worker not found", 404)), 404

    if user_updates:
        if "avatar" in user_updates:
            user_updates["profile_image_url"] = user_updates["avatar"]
        set_clause = ", ".join([f"{k} = ?" for k in user_updates.keys()])
        values = list(user_updates.values()) + [user_id]
        cursor.execute(f"UPDATE Users SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?", tuple(values))

    if profile_updates:
        set_clause = ", ".join([f"{k} = ?" for k in profile_updates.keys()])
        values = list(profile_updates.values()) + [user_id]
        cursor.execute(f"UPDATE worker_profiles SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?", tuple(values))
        if cursor.rowcount == 0:
            cursor.execute(
                "INSERT INTO worker_profiles (user_id, profession) VALUES (?, ?)",
                (user_id, profile_updates.get("profession")),
            )

    conn.commit()
    conn.close()
    _invalidate_cache()
    _invalidate_workers_public_cache()
    _invalidate_worker_dashboard_cache(user_id)
    return jsonify(response({"user_id": user_id}, "Worker updated", 200)), 200


@admin_api.route("/messageworkers/conversations", methods=["GET"])
@admin_required
def message_workers_conversations():
    conn, cursor = db_connection()
    rows = _conversation_list(cursor, _admin_id(), conv_type="worker_admin")
    conn.close()
    return jsonify(response(rows, "Conversations fetched", 200)), 200


@admin_api.route("/messageworkers/send", methods=["POST"])
@admin_required
@rate_limit("admin-messageworkers-send", limit=20, window_seconds=60)
def message_workers_send():
    data = request.get_json() or {}
    worker_id = data.get("worker_id")
    body = (data.get("body") or "").strip()
    channel = (data.get("channel") or "in_app").strip().lower()
    if not worker_id or not body:
        return jsonify(response(None, "worker_id and body are required", 400)), 400
    if channel not in {"in_app", "whatsapp", "email"}:
        return jsonify(response(None, "Invalid channel", 400)), 400

    conn, cursor = db_connection()
    cursor.execute("SELECT id FROM Users WHERE id = ? AND LOWER(user_type) = 'worker'", (worker_id,))
    if not cursor.fetchone():
        conn.close()
        return jsonify(response(None, "Worker user not found", 404)), 404

    conversation_id = _ensure_conversation(cursor, "worker_admin", _admin_id(), int(worker_id))
    cursor.execute(
        "INSERT INTO messages (conversation_id, sender_id, body, channel) VALUES (?, ?, ?, ?)",
        (conversation_id, _admin_id(), body, channel),
    )
    message_id = cursor.lastrowid
    _notify(cursor, int(worker_id), "message", "New admin message", body, {"conversation_id": conversation_id, "message_id": message_id})
    conn.commit()
    conn.close()
    _invalidate_worker_dashboard_cache(int(worker_id))
    return jsonify(response({"conversation_id": conversation_id, "message_id": message_id}, "Message sent", 201)), 201


@admin_api.route("/notifications", methods=["GET"])
@admin_required
def admin_notifications_list():
    page, per_page, offset = parse_pagination(request.args)
    conn, cursor = db_connection()
    cursor.execute("SELECT COUNT(*) AS total FROM admin_notifications")
    total = int(cursor.fetchone()["total"] or 0)
    cursor.execute(
        """
        SELECT id, type, title, description, href, read, created_at
        FROM admin_notifications
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
        """,
        (per_page, offset),
    )
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    meta = build_meta(page, per_page, total)
    return jsonify(envelope(rows, "Admin notifications fetched", 200, True, meta)), 200


@admin_api.route("/notifications", methods=["POST"])
@admin_required
def admin_notifications_create():
    data = request.get_json() or {}
    notification_type = str(data.get("type") or "").strip().lower()
    title = str(data.get("title") or "").strip()
    description = str(data.get("description") or "").strip()
    href = str(data.get("href") or "").strip() or None

    if notification_type not in {"order", "message", "system"}:
        return jsonify(envelope(None, "type must be order|message|system", 400, False)), 400
    if not title:
        return jsonify(envelope(None, "title is required", 400, False)), 400

    notification_id = str(uuid.uuid4())
    conn, cursor = db_connection()
    cursor.execute(
        """
        INSERT INTO admin_notifications (id, type, title, description, href, read)
        VALUES (?, ?, ?, ?, ?, 0)
        """,
        (notification_id, notification_type, title, description, href),
    )
    conn.commit()
    conn.close()
    payload = {
        "id": notification_id,
        "type": notification_type,
        "title": title,
        "description": description,
        "href": href,
        "read": 0,
    }
    return jsonify(envelope(payload, "Admin notification created", 201)), 201


@admin_api.route("/notifications/<notification_id>/read", methods=["PATCH"])
@admin_required
def admin_notifications_mark_read(notification_id):
    conn, cursor = db_connection()
    cursor.execute(
        """
        UPDATE admin_notifications
        SET read = 1
        WHERE id = ?
        """,
        (notification_id,),
    )
    conn.commit()
    if cursor.rowcount == 0:
        conn.close()
        return jsonify(envelope(None, "Notification not found", 404, False)), 404
    conn.close()
    return jsonify(envelope({"id": notification_id, "read": 1}, "Notification marked as read", 200)), 200


@admin_api.route("/notifications/read-all", methods=["PATCH"])
@admin_required
def admin_notifications_mark_all_read():
    conn, cursor = db_connection()
    cursor.execute("UPDATE admin_notifications SET read = 1 WHERE COALESCE(read, 0) = 0")
    updated = int(cursor.rowcount or 0)
    conn.commit()
    conn.close()
    return jsonify(envelope({"updated": updated}, "All notifications marked as read", 200)), 200


@admin_api.route("/services", methods=["GET"])
@admin_required
def admin_services_get():
    conn, cursor = db_connection()
    cursor.execute("SELECT * FROM services ORDER BY created_at DESC")
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify(response(rows, "Services fetched", 200)), 200


@admin_api.route("/services", methods=["POST"])
@admin_required
def admin_services_post():
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify(response(None, "name is required", 400)), 400
    conn, cursor = db_connection()
    cursor.execute(
        "INSERT INTO services (name, description, worker_type, base_price, is_active) VALUES (?, ?, ?, ?, ?)",
        (name, data.get("description"), data.get("worker_type"), data.get("base_price"), 1 if data.get("is_active", True) else 0),
    )
    service_id = cursor.lastrowid
    conn.commit()
    conn.close()
    _invalidate_cache()
    return jsonify(response({"id": service_id}, "Service created", 201)), 201


@admin_api.route("/services/<int:service_id>", methods=["PATCH"])
@admin_required
def admin_services_patch(service_id):
    data = request.get_json() or {}
    allowed = ["name", "description", "worker_type", "base_price", "is_active"]
    updates = {k: data[k] for k in allowed if k in data}
    if not updates:
        return jsonify(response(None, "No fields provided for update", 400)), 400
    set_clause = ", ".join([f"{k} = ?" for k in updates.keys()])
    values = list(updates.values()) + [service_id]
    conn, cursor = db_connection()
    cursor.execute(f"UPDATE services SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?", tuple(values))
    conn.commit()
    if cursor.rowcount == 0:
        conn.close()
        return jsonify(response(None, "Service not found", 404)), 404
    conn.close()
    _invalidate_cache()
    return jsonify(response({"id": service_id}, "Service updated", 200)), 200


@admin_api.route("/services/<int:service_id>", methods=["DELETE"])
@admin_required
def admin_services_delete(service_id):
    conn, cursor = db_connection()
    cursor.execute("DELETE FROM services WHERE id = ?", (service_id,))
    conn.commit()
    if cursor.rowcount == 0:
        conn.close()
        return jsonify(response(None, "Service not found", 404)), 404
    conn.close()
    _invalidate_cache()
    return jsonify(response({"id": service_id}, "Service deleted", 200)), 200

@admin_api.route("/jobs", methods=["GET"])
@admin_required
def admin_jobs_list():
    search = (request.args.get("search") or "").strip()
    status = (request.args.get("status") or "").strip().lower()
    page = request.args.get("page", default=1, type=int) or 1
    size = request.args.get("size", default=20, type=int) or 20
    if page < 1:
        page = 1
    if size < 1:
        size = 20
    offset = (page - 1) * size

    where = ["1=1"]
    params = []
    if search:
        like = f"%{search}%"
        where.append("(LOWER(COALESCE(b.code, '')) LIKE LOWER(?) OR LOWER(COALESCE(b.description, b.job_description, '')) LIKE LOWER(?))")
        params.extend([like, like])
    if status:
        where.append("LOWER(b.status) = ?")
        params.append(status)
    where_sql = " AND ".join(where)

    conn, cursor = db_connection()
    cursor.execute(f"SELECT COUNT(*) AS total FROM bookings b WHERE {where_sql}", tuple(params))
    total = cursor.fetchone()["total"]
    query_params = list(params) + [size, offset]
    cursor.execute(
        f"""
        SELECT b.*, cu.full_name AS customer_name, w.name AS worker_name
        FROM bookings b
        LEFT JOIN Users cu ON cu.id = b.customer_id
        LEFT JOIN Workers w ON w.id = b.worker_id
        WHERE {where_sql}
        ORDER BY b.created_at DESC
        LIMIT ? OFFSET ?
        """,
        tuple(query_params),
    )
    jobs = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify(response({"jobs": jobs, "page": page, "size": size, "total": total}, "Jobs fetched", 200)), 200


@admin_api.route("/jobs/<int:job_id>", methods=["GET"])
@admin_required
def admin_job_get(job_id):
    conn, cursor = db_connection()
    cursor.execute(
        """
        SELECT b.*, cu.full_name AS customer_name, w.name AS worker_name
        FROM bookings b
        LEFT JOIN Users cu ON cu.id = b.customer_id
        LEFT JOIN Workers w ON w.id = b.worker_id
        WHERE b.id = ?
        """,
        (job_id,),
    )
    row = cursor.fetchone()
    if not row:
        conn.close()
        return jsonify(response(None, "Job not found", 404)), 404
    job = dict(row)
    cursor.execute("SELECT * FROM job_status_history WHERE job_id = ? ORDER BY created_at DESC, id DESC", (job_id,))
    job["status_history"] = [dict(h) for h in cursor.fetchall()]
    conn.close()
    return jsonify(response(job, "Job fetched", 200)), 200


@admin_api.route("/jobs/<int:job_id>/status", methods=["PATCH"])
@admin_required
def admin_job_patch_status(job_id):
    data = request.get_json() or {}
    status = (data.get("status") or "").strip().lower()
    if status not in JOB_STATUSES:
        return jsonify(response(None, "Invalid status", 400)), 400
    conn, cursor = db_connection()
    cursor.execute("SELECT status, customer_id, worker_id FROM bookings WHERE id = ?", (job_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return jsonify(response(None, "Job not found", 404)), 404
    old_status = row["status"]
    cursor.execute("UPDATE bookings SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (status, job_id))
    cursor.execute(
        "INSERT INTO job_status_history (job_id, from_status, to_status, changed_by, note) VALUES (?, ?, ?, ?, ?)",
        (job_id, old_status, status, _admin_id(), data.get("note")),
    )
    if row["customer_id"]:
        _notify(cursor, row["customer_id"], "job_status", "Job status updated", f"New status: {status}", {"job_id": job_id})
    conn.commit()
    conn.close()
    _invalidate_cache()
    _invalidate_worker_dashboard_cache()
    return jsonify(response({"id": job_id, "status": status}, "Job status updated", 200)), 200


@admin_api.route("/jobs/<int:job_id>/price", methods=["PATCH"])
@admin_required
def admin_job_patch_price(job_id):
    data = request.get_json() or {}
    total_price = data.get("total_price")
    if total_price is None:
        return jsonify(response(None, "total_price is required", 400)), 400
    conn, cursor = db_connection()
    cursor.execute("UPDATE bookings SET total_price = ?, estimated_price = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (total_price, total_price, job_id))
    conn.commit()
    if cursor.rowcount == 0:
        conn.close()
        return jsonify(response(None, "Job not found", 404)), 404
    conn.close()
    _invalidate_cache()
    _invalidate_worker_dashboard_cache()
    return jsonify(response({"id": job_id, "total_price": total_price}, "Job price updated", 200)), 200


@admin_api.route("/jobs/<int:job_id>/note", methods=["PATCH"])
@admin_required
def admin_job_patch_note(job_id):
    data = request.get_json() or {}
    admin_note = data.get("admin_note")
    if admin_note is None:
        return jsonify(response(None, "admin_note is required", 400)), 400
    conn, cursor = db_connection()
    cursor.execute("UPDATE bookings SET admin_note = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (admin_note, job_id))
    conn.commit()
    if cursor.rowcount == 0:
        conn.close()
        return jsonify(response(None, "Job not found", 404)), 404
    conn.close()
    _invalidate_cache()
    _invalidate_worker_dashboard_cache()
    return jsonify(response({"id": job_id, "admin_note": admin_note}, "Job note updated", 200)), 200


@admin_api.route("/inventory/items", methods=["GET"])
@admin_required
def admin_inventory_get():
    conn, cursor = db_connection()
    cursor.execute("SELECT * FROM inventory_items ORDER BY created_at DESC")
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify(response(rows, "Inventory items fetched", 200)), 200


@admin_api.route("/inventory/items", methods=["POST"])
@admin_required
def admin_inventory_post():
    data = request.get_json() or {}
    sku = (data.get("sku") or "").strip()
    name = (data.get("name") or "").strip()
    if not sku or not name:
        return jsonify(response(None, "sku and name are required", 400)), 400
    conn, cursor = db_connection()
    cursor.execute(
        """
        INSERT INTO inventory_items (sku, name, category, quantity, unit_cost, reorder_level, is_active)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (sku, name, data.get("category"), data.get("quantity", 0), data.get("unit_cost", 0), data.get("reorder_level", 0), 1 if data.get("is_active", True) else 0),
    )
    item_id = cursor.lastrowid
    conn.commit()
    conn.close()
    _invalidate_cache()
    return jsonify(response({"id": item_id}, "Inventory item created", 201)), 201


@admin_api.route("/inventory/items/<int:item_id>", methods=["PATCH"])
@admin_required
def admin_inventory_patch(item_id):
    data = request.get_json() or {}
    allowed = ["name", "category", "quantity", "unit_cost", "reorder_level", "is_active"]
    updates = {k: data[k] for k in allowed if k in data}
    if not updates:
        return jsonify(response(None, "No fields provided for update", 400)), 400
    set_clause = ", ".join([f"{k} = ?" for k in updates.keys()])
    values = list(updates.values()) + [item_id]
    conn, cursor = db_connection()
    cursor.execute(f"UPDATE inventory_items SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?", tuple(values))
    conn.commit()
    if cursor.rowcount == 0:
        conn.close()
        return jsonify(response(None, "Inventory item not found", 404)), 404
    conn.close()
    _invalidate_cache()
    return jsonify(response({"id": item_id}, "Inventory item updated", 200)), 200


@admin_api.route("/inventory/items/<int:item_id>", methods=["DELETE"])
@admin_required
def admin_inventory_delete(item_id):
    conn, cursor = db_connection()
    cursor.execute("DELETE FROM inventory_items WHERE id = ?", (item_id,))
    conn.commit()
    if cursor.rowcount == 0:
        conn.close()
        return jsonify(response(None, "Inventory item not found", 404)), 404
    conn.close()
    _invalidate_cache()
    return jsonify(response({"id": item_id}, "Inventory item deleted", 200)), 200


@admin_api.route("/sync/status", methods=["GET"])
@admin_required
def admin_sync_status():
    conn, cursor = db_connection()
    cursor.execute("SELECT * FROM sync_runs WHERE status = 'running' ORDER BY started_at DESC LIMIT 1")
    running = cursor.fetchone()
    cursor.execute("SELECT * FROM sync_runs ORDER BY started_at DESC LIMIT 1")
    latest = cursor.fetchone()
    conn.close()
    return jsonify(response({"running": dict(running) if running else None, "latest": dict(latest) if latest else None}, "Sync status fetched", 200)), 200


@admin_api.route("/sync/run", methods=["POST"])
@admin_required
def admin_sync_run():
    data = request.get_json() or {}
    source = data.get("source") or "manual"
    log_text = data.get("log_text") or "Sync completed"
    conn, cursor = db_connection()
    cursor.execute("INSERT INTO sync_runs (source, status, started_at) VALUES (?, 'running', CURRENT_TIMESTAMP)", (source,))
    run_id = cursor.lastrowid
    cursor.execute("UPDATE sync_runs SET status = 'success', ended_at = CURRENT_TIMESTAMP, log_text = ? WHERE id = ?", (log_text, run_id))
    conn.commit()
    conn.close()
    return jsonify(response({"id": run_id, "status": "success"}, "Sync run completed", 201)), 201


@admin_api.route("/sync/logs", methods=["GET"])
@admin_required
def admin_sync_logs():
    conn, cursor = db_connection()
    cursor.execute("SELECT * FROM sync_runs ORDER BY started_at DESC, id DESC")
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify(response(rows, "Sync logs fetched", 200)), 200

@admin_api.route("/payments/summary", methods=["GET"])
@admin_required
def admin_payments_summary():
    conn, cursor = db_connection()
    cursor.execute("SELECT COALESCE(SUM(balance), 0) AS v FROM wallets")
    total_balance = cursor.fetchone()["v"]
    cursor.execute("SELECT COALESCE(SUM(pending_balance), 0) AS v FROM wallets")
    pending_balance = cursor.fetchone()["v"]
    cursor.execute("SELECT COALESCE(SUM(amount), 0) AS v FROM wallet_transactions WHERE type = 'credit'")
    total_credit = cursor.fetchone()["v"]
    cursor.execute("SELECT COALESCE(SUM(amount), 0) AS v FROM wallet_transactions WHERE type = 'debit'")
    total_debit = cursor.fetchone()["v"]
    conn.close()
    return jsonify(response({"total_balance": total_balance, "pending_balance": pending_balance, "total_credit": total_credit, "total_debit": total_debit}, "Payments summary fetched", 200)), 200


@admin_api.route("/payments/transactions", methods=["GET"])
@admin_required
def admin_payments_transactions():
    conn, cursor = db_connection()
    cursor.execute(
        """
        SELECT t.*, w.user_id, u.full_name, u.email
        FROM wallet_transactions t
        JOIN wallets w ON w.id = t.wallet_id
        JOIN Users u ON u.id = w.user_id
        ORDER BY t.created_at DESC, t.id DESC
        """
    )
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify(response(rows, "Transactions fetched", 200)), 200


@admin_api.route("/payments/worker-payout", methods=["POST"])
@admin_required
def admin_worker_payout():
    data = request.get_json() or {}
    worker_id = data.get("worker_id")
    amount = data.get("amount")
    if worker_id is None or amount is None:
        return jsonify(response(None, "worker_id and amount are required", 400)), 400

    worker_id = int(worker_id)
    amount = float(amount)
    if amount <= 0:
        return jsonify(response(None, "amount must be > 0", 400)), 400

    conn, cursor = db_connection()
    cursor.execute("SELECT id FROM Users WHERE id = ? AND LOWER(user_type) = 'worker'", (worker_id,))
    if not cursor.fetchone():
        conn.close()
        return jsonify(response(None, "Worker user not found", 404)), 404
    wallet_id = _ensure_wallet(cursor, worker_id)
    cursor.execute("SELECT balance FROM wallets WHERE id = ?", (wallet_id,))
    balance = float(cursor.fetchone()["balance"])
    if balance < amount:
        conn.close()
        return jsonify(response(None, "Insufficient wallet balance", 400)), 400

    reference = data.get("reference") or f"payout-{uuid.uuid4().hex[:10]}"
    cursor.execute("UPDATE wallets SET balance = balance - ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (amount, wallet_id))
    cursor.execute(
        "INSERT INTO wallet_transactions (wallet_id, type, amount, title, reference, status) VALUES (?, 'debit', ?, ?, ?, 'paid')",
        (wallet_id, amount, data.get("title") or "Worker payout", reference),
    )
    tx_id = cursor.lastrowid
    cursor.execute(
        """
        INSERT INTO withdrawal_requests (
            worker_id, amount, bank_name, account_number_masked, status, processed_by, processed_at
        ) VALUES (?, ?, ?, ?, 'paid', ?, CURRENT_TIMESTAMP)
        """,
        (worker_id, amount, data.get("bank_name"), data.get("account_number_masked"), _admin_id()),
    )
    wr_id = cursor.lastrowid
    _notify(cursor, worker_id, "payout", "Payout completed", f"Payout of {amount:.2f} has been processed.", {"transaction_id": tx_id, "withdrawal_id": wr_id})
    conn.commit()
    conn.close()
    _invalidate_cache()
    _invalidate_worker_dashboard_cache(worker_id)
    return jsonify(response({"transaction_id": tx_id, "withdrawal_request_id": wr_id}, "Worker payout processed", 201)), 201


@admin_api.route("/settings", methods=["GET"])
@admin_required
def admin_settings_get():
    conn, cursor = db_connection()
    cursor.execute("SELECT key, value_json FROM admin_settings ORDER BY key ASC")
    rows = cursor.fetchall()
    conn.close()
    settings = {}
    for row in rows:
        try:
            settings[row["key"]] = json.loads(row["value_json"]) if row["value_json"] else None
        except Exception:
            settings[row["key"]] = row["value_json"]
    return jsonify(response(settings, "Settings fetched", 200)), 200


@admin_api.route("/settings", methods=["PATCH"])
@admin_required
def admin_settings_patch():
    data = request.get_json() or {}
    updates = data.get("settings") if isinstance(data.get("settings"), dict) else data
    if not isinstance(updates, dict) or not updates:
        return jsonify(response(None, "No settings provided", 400)), 400
    conn, cursor = db_connection()
    for key, value in updates.items():
        cursor.execute(
            """
            INSERT INTO admin_settings (key, value_json, updated_by, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET
                value_json = excluded.value_json,
                updated_by = excluded.updated_by,
                updated_at = CURRENT_TIMESTAMP
            """,
            (str(key), json.dumps(value), _admin_id()),
        )
    conn.commit()
    conn.close()
    _invalidate_cache()
    return jsonify(response({}, "Settings updated", 200)), 200
