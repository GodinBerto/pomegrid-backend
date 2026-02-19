import json
import logging

from flask import Blueprint, g, jsonify, request

from database import db_connection
from decorators.rate_limit import rate_limit
from decorators.roles import worker_required
from extensions.redis_client import get_redis_client
from routes import response


worker_api = Blueprint("worker_api", __name__)
logger = logging.getLogger(__name__)


def _worker_id():
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


def _invalidate_worker_cache(user_id):
    try:
        redis_client = get_redis_client()
        keys = redis_client.keys(f"worker:dashboard:summary:{user_id}")
        if keys:
            redis_client.delete(*keys)
    except Exception:
        pass


def _invalidate_admin_cache():
    try:
        redis_client = get_redis_client()
        keys = redis_client.keys("admin:*")
        if keys:
            redis_client.delete(*keys)
    except Exception:
        pass


def _legacy_worker_id(cursor, user_id):
    cursor.execute("SELECT legacy_worker_id FROM worker_profiles WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if row and row["legacy_worker_id"]:
        return int(row["legacy_worker_id"])
    return user_id


def _ensure_wallet(cursor, user_id):
    cursor.execute("SELECT id FROM wallets WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if row:
        return row["id"]
    cursor.execute("INSERT INTO wallets (user_id, balance, pending_balance) VALUES (?, 0, 0)", (user_id,))
    return cursor.lastrowid


def _notify(cursor, user_id, notification_type, title, message, payload=None):
    cursor.execute(
        """
        INSERT INTO notifications (user_id, type, title, message, is_read, payload_json)
        VALUES (?, ?, ?, ?, 0, ?)
        """,
        (user_id, notification_type, title, message, json.dumps(payload or {})),
    )


@worker_api.route("/dashboard/summary", methods=["GET"])
@worker_required
def worker_dashboard_summary():
    worker_user_id = _worker_id()
    cache_key = f"worker:dashboard:summary:{worker_user_id}"
    cached = _cache_get(cache_key)
    if cached:
        return jsonify(response(cached, "Dashboard summary", 200)), 200

    conn, cursor = db_connection()
    legacy_worker = _legacy_worker_id(cursor, worker_user_id)

    cursor.execute("SELECT COUNT(*) AS c FROM bookings WHERE worker_id = ?", (legacy_worker,))
    total_jobs = cursor.fetchone()["c"]
    cursor.execute("SELECT COUNT(*) AS c FROM bookings WHERE worker_id = ? AND status = 'pending'", (legacy_worker,))
    pending_jobs = cursor.fetchone()["c"]
    cursor.execute("SELECT COUNT(*) AS c FROM bookings WHERE worker_id = ? AND status IN ('confirmed', 'in_progress', 'accepted')", (legacy_worker,))
    active_jobs = cursor.fetchone()["c"]
    cursor.execute("SELECT COUNT(*) AS c FROM bookings WHERE worker_id = ? AND status = 'completed'", (legacy_worker,))
    completed_jobs = cursor.fetchone()["c"]

    wallet_id = _ensure_wallet(cursor, worker_user_id)
    cursor.execute("SELECT balance, pending_balance FROM wallets WHERE id = ?", (wallet_id,))
    wallet = cursor.fetchone()

    cursor.execute("SELECT COUNT(*) AS c FROM notifications WHERE user_id = ? AND is_read = 0", (worker_user_id,))
    unread_notifications = cursor.fetchone()["c"]

    conn.commit()
    conn.close()

    payload = {
        "total_jobs": total_jobs,
        "pending_jobs": pending_jobs,
        "active_jobs": active_jobs,
        "completed_jobs": completed_jobs,
        "balance": wallet["balance"] if wallet else 0,
        "pending_balance": wallet["pending_balance"] if wallet else 0,
        "unread_notifications": unread_notifications,
    }
    _cache_set(cache_key, payload)
    return jsonify(response(payload, "Dashboard summary", 200)), 200


@worker_api.route("/jobs", methods=["GET"])
@worker_required
def worker_jobs_list():
    status = (request.args.get("status") or "").strip().lower()
    worker_user_id = _worker_id()

    conn, cursor = db_connection()
    legacy_worker = _legacy_worker_id(cursor, worker_user_id)

    where = ["worker_id = ?"]
    params = [legacy_worker]
    if status:
        where.append("LOWER(status) = ?")
        params.append(status)
    cursor.execute(
        f"SELECT * FROM bookings WHERE {' AND '.join(where)} ORDER BY created_at DESC",
        tuple(params),
    )
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify(response(rows, "Jobs fetched", 200)), 200


@worker_api.route("/jobs/<int:job_id>", methods=["GET"])
@worker_required
def worker_job_get(job_id):
    worker_user_id = _worker_id()
    conn, cursor = db_connection()
    legacy_worker = _legacy_worker_id(cursor, worker_user_id)
    cursor.execute("SELECT * FROM bookings WHERE id = ? AND worker_id = ?", (job_id, legacy_worker))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return jsonify(response(None, "Job not found", 404)), 404
    job = dict(row)
    cursor.execute("SELECT * FROM job_status_history WHERE job_id = ? ORDER BY created_at DESC, id DESC", (job_id,))
    job["status_history"] = [dict(h) for h in cursor.fetchall()]
    conn.close()
    return jsonify(response(job, "Job fetched", 200)), 200

@worker_api.route("/jobs/<int:job_id>/accept", methods=["PATCH"])
@worker_required
def worker_job_accept(job_id):
    return _worker_update_job_status(job_id, "confirmed")


@worker_api.route("/jobs/<int:job_id>/start", methods=["PATCH"])
@worker_required
def worker_job_start(job_id):
    return _worker_update_job_status(job_id, "in_progress")


@worker_api.route("/jobs/<int:job_id>/complete", methods=["PATCH"])
@worker_required
def worker_job_complete(job_id):
    return _worker_update_job_status(job_id, "completed")


def _worker_update_job_status(job_id, new_status):
    worker_user_id = _worker_id()
    conn, cursor = db_connection()
    legacy_worker = _legacy_worker_id(cursor, worker_user_id)
    cursor.execute("SELECT id, status, customer_id FROM bookings WHERE id = ? AND worker_id = ?", (job_id, legacy_worker))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return jsonify(response(None, "Job not found", 404)), 404

    cursor.execute("UPDATE bookings SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (new_status, job_id))
    cursor.execute(
        "INSERT INTO job_status_history (job_id, from_status, to_status, changed_by, note) VALUES (?, ?, ?, ?, ?)",
        (job_id, row["status"], new_status, worker_user_id, None),
    )
    if row["customer_id"]:
        _notify(cursor, row["customer_id"], "job_status", "Job updated", f"Your booking is now {new_status}", {"job_id": job_id})
    conn.commit()
    conn.close()
    _invalidate_worker_cache(worker_user_id)
    _invalidate_admin_cache()
    return jsonify(response({"id": job_id, "status": new_status}, "Job updated", 200)), 200


@worker_api.route("/funds/summary", methods=["GET"])
@worker_required
def worker_funds_summary():
    worker_user_id = _worker_id()
    conn, cursor = db_connection()
    wallet_id = _ensure_wallet(cursor, worker_user_id)
    cursor.execute("SELECT balance, pending_balance FROM wallets WHERE id = ?", (wallet_id,))
    wallet = cursor.fetchone()
    cursor.execute("SELECT COALESCE(SUM(amount), 0) AS v FROM wallet_transactions WHERE wallet_id = ? AND type = 'credit'", (wallet_id,))
    total_credit = cursor.fetchone()["v"]
    cursor.execute("SELECT COALESCE(SUM(amount), 0) AS v FROM wallet_transactions WHERE wallet_id = ? AND type = 'debit'", (wallet_id,))
    total_debit = cursor.fetchone()["v"]
    conn.commit()
    conn.close()
    payload = {
        "wallet_id": wallet_id,
        "balance": wallet["balance"] if wallet else 0,
        "pending_balance": wallet["pending_balance"] if wallet else 0,
        "total_credit": total_credit,
        "total_debit": total_debit,
    }
    return jsonify(response(payload, "Funds summary fetched", 200)), 200


@worker_api.route("/funds/transactions", methods=["GET"])
@worker_required
def worker_funds_transactions():
    worker_user_id = _worker_id()
    conn, cursor = db_connection()
    wallet_id = _ensure_wallet(cursor, worker_user_id)
    cursor.execute("SELECT * FROM wallet_transactions WHERE wallet_id = ? ORDER BY created_at DESC, id DESC", (wallet_id,))
    rows = [dict(row) for row in cursor.fetchall()]
    conn.commit()
    conn.close()
    return jsonify(response(rows, "Transactions fetched", 200)), 200


@worker_api.route("/funds/withdrawals", methods=["POST"])
@worker_required
def worker_create_withdrawal():
    worker_user_id = _worker_id()
    data = request.get_json() or {}
    amount = data.get("amount")
    if amount is None:
        return jsonify(response(None, "amount is required", 400)), 400
    amount = float(amount)
    if amount <= 0:
        return jsonify(response(None, "amount must be > 0", 400)), 400

    conn, cursor = db_connection()
    wallet_id = _ensure_wallet(cursor, worker_user_id)
    cursor.execute("SELECT balance FROM wallets WHERE id = ?", (wallet_id,))
    wallet = cursor.fetchone()
    balance = float(wallet["balance"] if wallet else 0)
    if balance < amount:
        conn.close()
        return jsonify(response(None, "Insufficient wallet balance", 400)), 400

    cursor.execute(
        "UPDATE wallets SET balance = balance - ?, pending_balance = pending_balance + ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (amount, amount, wallet_id),
    )
    cursor.execute(
        """
        INSERT INTO withdrawal_requests (
            worker_id, amount, bank_name, account_number_masked, status
        ) VALUES (?, ?, ?, ?, 'pending')
        """,
        (worker_user_id, amount, data.get("bank_name"), data.get("account_number_masked")),
    )
    withdrawal_id = cursor.lastrowid
    cursor.execute(
        "INSERT INTO wallet_transactions (wallet_id, type, amount, title, reference, status) VALUES (?, 'debit', ?, ?, ?, 'pending')",
        (wallet_id, amount, "Withdrawal request", data.get("reference") or f"wd-{withdrawal_id}"),
    )
    conn.commit()
    conn.close()
    _invalidate_worker_cache(worker_user_id)
    _invalidate_admin_cache()
    return jsonify(response({"withdrawal_id": withdrawal_id}, "Withdrawal request created", 201)), 201


@worker_api.route("/reviews", methods=["GET"])
@worker_required
def worker_reviews():
    worker_user_id = _worker_id()
    conn, cursor = db_connection()
    cursor.execute(
        """
        SELECT r.*, u.full_name AS customer_name
        FROM reviews r
        LEFT JOIN Users u ON u.id = r.customer_id
        WHERE r.worker_id = ?
        ORDER BY r.created_at DESC, r.id DESC
        """,
        (worker_user_id,),
    )
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify(response(rows, "Reviews fetched", 200)), 200


@worker_api.route("/notifications", methods=["GET"])
@worker_required
def worker_notifications():
    worker_user_id = _worker_id()
    conn, cursor = db_connection()
    cursor.execute(
        "SELECT * FROM notifications WHERE user_id = ? ORDER BY created_at DESC, id DESC",
        (worker_user_id,),
    )
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify(response(rows, "Notifications fetched", 200)), 200


@worker_api.route("/notifications/read-all", methods=["PATCH"])
@worker_required
def worker_notifications_read_all():
    worker_user_id = _worker_id()
    conn, cursor = db_connection()
    cursor.execute("UPDATE notifications SET is_read = 1 WHERE user_id = ?", (worker_user_id,))
    conn.commit()
    conn.close()
    _invalidate_worker_cache(worker_user_id)
    return jsonify(response({}, "Notifications marked as read", 200)), 200


@worker_api.route("/notifications/<int:notification_id>/read", methods=["PATCH"])
@worker_required
def worker_notification_read(notification_id):
    worker_user_id = _worker_id()
    conn, cursor = db_connection()
    cursor.execute("UPDATE notifications SET is_read = 1 WHERE id = ? AND user_id = ?", (notification_id, worker_user_id))
    conn.commit()
    if cursor.rowcount == 0:
        conn.close()
        return jsonify(response(None, "Notification not found", 404)), 404
    conn.close()
    _invalidate_worker_cache(worker_user_id)
    return jsonify(response({"id": notification_id}, "Notification marked as read", 200)), 200

@worker_api.route("/messages/conversations", methods=["GET"])
@worker_required
def worker_conversations():
    worker_user_id = _worker_id()
    conn, cursor = db_connection()
    cursor.execute(
        """
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
        WHERE cp.user_id = ?
        GROUP BY c.id
        ORDER BY COALESCE(MAX(m.created_at), c.created_at) DESC
        """,
        (worker_user_id,),
    )
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify(response(rows, "Conversations fetched", 200)), 200


@worker_api.route("/messages/conversations/<int:conversation_id>/messages", methods=["GET"])
@worker_required
def worker_conversation_messages(conversation_id):
    worker_user_id = _worker_id()
    conn, cursor = db_connection()
    cursor.execute("SELECT 1 FROM conversation_participants WHERE conversation_id = ? AND user_id = ?", (conversation_id, worker_user_id))
    if not cursor.fetchone():
        conn.close()
        return jsonify(response(None, "Conversation not found", 404)), 404
    cursor.execute(
        """
        SELECT m.*, u.full_name AS sender_name
        FROM messages m
        JOIN Users u ON u.id = m.sender_id
        WHERE m.conversation_id = ?
        ORDER BY m.created_at ASC, m.id ASC
        """,
        (conversation_id,),
    )
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify(response(rows, "Messages fetched", 200)), 200


@worker_api.route("/messages/conversations/<int:conversation_id>/messages", methods=["POST"])
@worker_required
@rate_limit("worker-messages-send", limit=30, window_seconds=60)
def worker_conversation_send(conversation_id):
    worker_user_id = _worker_id()
    data = request.get_json() or {}
    body = (data.get("body") or "").strip()
    channel = (data.get("channel") or "in_app").strip().lower()
    if not body:
        return jsonify(response(None, "body is required", 400)), 400
    if channel not in {"in_app", "whatsapp", "email"}:
        return jsonify(response(None, "Invalid channel", 400)), 400

    conn, cursor = db_connection()
    cursor.execute("SELECT 1 FROM conversation_participants WHERE conversation_id = ? AND user_id = ?", (conversation_id, worker_user_id))
    if not cursor.fetchone():
        conn.close()
        return jsonify(response(None, "Conversation not found", 404)), 404

    cursor.execute(
        "INSERT INTO messages (conversation_id, sender_id, body, channel) VALUES (?, ?, ?, ?)",
        (conversation_id, worker_user_id, body, channel),
    )
    message_id = cursor.lastrowid
    cursor.execute("SELECT user_id FROM conversation_participants WHERE conversation_id = ? AND user_id != ?", (conversation_id, worker_user_id))
    for row in cursor.fetchall():
        _notify(cursor, row["user_id"], "message", "New message", body, {"conversation_id": conversation_id, "message_id": message_id})
    conn.commit()
    conn.close()
    return jsonify(response({"message_id": message_id}, "Message sent", 201)), 201


@worker_api.route("/settings", methods=["GET"])
@worker_required
def worker_settings_get():
    worker_user_id = _worker_id()
    conn, cursor = db_connection()
    cursor.execute(
        """
        SELECT
            u.id, u.email, u.full_name, u.phone, u.user_type,
            u.address, u.avatar, u.date_of_birth,
            wp.profession, wp.bio, wp.location, wp.hourly_rate, wp.is_available
        FROM Users u
        LEFT JOIN worker_profiles wp ON wp.user_id = u.id
        WHERE u.id = ?
        """,
        (worker_user_id,),
    )
    row = cursor.fetchone()
    conn.close()
    if not row:
        return jsonify(response(None, "Worker profile not found", 404)), 404
    return jsonify(response(dict(row), "Settings fetched", 200)), 200


@worker_api.route("/settings", methods=["PATCH"])
@worker_required
def worker_settings_patch():
    worker_user_id = _worker_id()
    data = request.get_json() or {}
    user_allowed = ["full_name", "phone", "address", "avatar", "date_of_birth"]
    profile_allowed = ["profession", "bio", "location", "hourly_rate", "is_available"]
    user_updates = {k: data[k] for k in user_allowed if k in data}
    profile_updates = {k: data[k] for k in profile_allowed if k in data}
    if not user_updates and not profile_updates:
        return jsonify(response(None, "No fields provided for update", 400)), 400

    conn, cursor = db_connection()
    if user_updates:
        if "avatar" in user_updates:
            user_updates["profile_image_url"] = user_updates["avatar"]
        set_clause = ", ".join([f"{k} = ?" for k in user_updates.keys()])
        values = list(user_updates.values()) + [worker_user_id]
        cursor.execute(f"UPDATE Users SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?", tuple(values))

    if profile_updates:
        set_clause = ", ".join([f"{k} = ?" for k in profile_updates.keys()])
        values = list(profile_updates.values()) + [worker_user_id]
        cursor.execute(f"UPDATE worker_profiles SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?", tuple(values))
        if cursor.rowcount == 0:
            cursor.execute("INSERT INTO worker_profiles (user_id, profession) VALUES (?, ?)", (worker_user_id, profile_updates.get("profession")))

    conn.commit()
    conn.close()
    _invalidate_worker_cache(worker_user_id)
    return jsonify(response({}, "Settings updated", 200)), 200
