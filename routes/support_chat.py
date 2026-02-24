import uuid
from datetime import datetime, timezone


MESSAGE_MAX_LENGTH = 2000


def validate_message_content(raw_content, max_length=MESSAGE_MAX_LENGTH):
    content = str(raw_content or "").strip()
    if not content:
        return None, "content is required"
    if len(content) > int(max_length):
        return None, f"content must be at most {int(max_length)} characters"
    return content, None


def to_iso_utc(value):
    if value is None:
        return None

    raw = str(value).strip()
    if not raw:
        return None

    normalized = raw.replace(" ", "T")
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"

    dt_obj = None
    try:
        dt_obj = datetime.fromisoformat(normalized)
    except ValueError:
        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
        ):
            try:
                dt_obj = datetime.strptime(raw, fmt)
                break
            except ValueError:
                continue

    if dt_obj is None:
        return raw

    if dt_obj.tzinfo is None:
        dt_obj = dt_obj.replace(tzinfo=timezone.utc)
    else:
        dt_obj = dt_obj.astimezone(timezone.utc)
    return dt_obj.isoformat().replace("+00:00", "Z")


def list_response(key, items, message, status=200, meta=None):
    payload = {
        "success": True,
        "status": int(status),
        "message": message,
        key: items,
        "data": items,
    }
    if meta is not None:
        payload["meta"] = meta
    return payload


def single_response(key, item, message, status=200):
    return {
        "success": True,
        "status": int(status),
        "message": message,
        key: item,
        "data": item,
    }


def error_response(message, status=400):
    return {
        "success": False,
        "status": int(status),
        "message": message,
        "data": None,
    }


def _conversation_sort_sql():
    return "COALESCE(c.last_message_at, c.updated_at, c.created_at) DESC, c.created_at DESC"


def get_support_conversation_id_for_user(cursor, user_id):
    cursor.execute(
        f"""
        SELECT c.id
        FROM admin_conversations c
        WHERE c.user_id = ?
        ORDER BY {_conversation_sort_sql()}
        LIMIT 1
        """,
        (int(user_id),),
    )
    row = cursor.fetchone()
    return str(row["id"]) if row else None


def ensure_support_conversation(cursor, user_id, admin_id=None):
    existing_id = get_support_conversation_id_for_user(cursor, user_id)
    if existing_id:
        return existing_id, False

    conversation_id = str(uuid.uuid4())
    cursor.execute(
        """
        INSERT INTO admin_conversations (id, user_id, admin_id, created_at, updated_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """,
        (conversation_id, int(user_id), int(admin_id) if admin_id is not None else None),
    )
    return conversation_id, True


def get_active_admin_id(cursor):
    cursor.execute(
        """
        SELECT id
        FROM Users
        WHERE COALESCE(is_active, 1) = 1
          AND (
            LOWER(COALESCE(role, '')) = 'admin'
            OR LOWER(COALESCE(user_type, '')) = 'admin'
            OR COALESCE(is_admin, 0) = 1
          )
        ORDER BY id ASC
        LIMIT 1
        """
    )
    row = cursor.fetchone()
    return int(row["id"]) if row else None


def has_support_conversation_access(cursor, conversation_id, user_id, is_admin=False):
    if bool(is_admin):
        cursor.execute("SELECT 1 FROM admin_conversations WHERE id = ?", (str(conversation_id),))
    else:
        cursor.execute(
            "SELECT 1 FROM admin_conversations WHERE id = ? AND user_id = ?",
            (str(conversation_id), int(user_id)),
        )
    return cursor.fetchone() is not None


def get_conversation_owner_id(cursor, conversation_id):
    cursor.execute(
        "SELECT user_id FROM admin_conversations WHERE id = ?",
        (str(conversation_id),),
    )
    row = cursor.fetchone()
    return int(row["user_id"]) if row else None


def touch_conversation(cursor, conversation_id, admin_id=None):
    if admin_id is None:
        cursor.execute(
            """
            UPDATE admin_conversations
            SET last_message_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (str(conversation_id),),
        )
        return

    cursor.execute(
        """
        UPDATE admin_conversations
        SET admin_id = ?,
            last_message_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (int(admin_id), str(conversation_id)),
    )


def create_support_message(cursor, conversation_id, sender_id, receiver_id, content):
    cursor.execute(
        """
        INSERT INTO admin_messages (conversation_id, sender_id, receiver_id, content, is_read, created_at)
        VALUES (?, ?, ?, ?, 0, CURRENT_TIMESTAMP)
        """,
        (str(conversation_id), int(sender_id), int(receiver_id), str(content)),
    )
    return int(cursor.lastrowid)


def mark_messages_as_read(cursor, conversation_id, receiver_id):
    cursor.execute(
        """
        UPDATE admin_messages
        SET is_read = 1
        WHERE conversation_id = ?
          AND receiver_id = ?
          AND COALESCE(is_read, 0) = 0
        """,
        (str(conversation_id), int(receiver_id)),
    )
    return int(cursor.rowcount or 0)


def mark_messages_as_read_for_admin(cursor, conversation_id):
    cursor.execute(
        """
        UPDATE admin_messages
        SET is_read = 1
        WHERE conversation_id = ?
          AND COALESCE(is_read, 0) = 0
          AND sender_id = (
              SELECT user_id
              FROM admin_conversations
              WHERE id = ?
          )
        """,
        (str(conversation_id), str(conversation_id)),
    )
    return int(cursor.rowcount or 0)


def _serialize_conversation(row):
    conversation_id = str(row["id"])
    latest_message = row["latest_message"]
    return {
        "id": conversation_id,
        "user_id": int(row["user_id"]) if row["user_id"] is not None else None,
        "admin_id": int(row["admin_id"]) if row["admin_id"] is not None else None,
        "user_name": row["user_name"],
        "user_email": row["user_email"],
        "last_message_at": to_iso_utc(row["last_message_at"]),
        "unread_count": int(row["unread_count"] or 0),
        "latest_message": latest_message,
        "last_message": latest_message,
        "created_at": to_iso_utc(row["created_at"]),
        "updated_at": to_iso_utc(row["updated_at"]),
    }


def _serialize_message(row):
    return {
        "id": int(row["id"]),
        "conversation_id": str(row["conversation_id"]),
        "sender_id": int(row["sender_id"]),
        "receiver_id": int(row["receiver_id"]),
        "content": row["content"],
        "is_read": bool(row["is_read"]),
        "created_at": to_iso_utc(row["created_at"]),
        "sender_name": row["sender_name"],
        "receiver_name": row["receiver_name"],
    }


def fetch_support_conversations(cursor, viewer_id, limit, offset, viewer_is_admin=False):
    cursor.execute("SELECT COUNT(DISTINCT user_id) AS total FROM admin_conversations")
    total = int(cursor.fetchone()["total"] or 0)

    if bool(viewer_is_admin):
        unread_clause = """
            (
                SELECT COUNT(*)
                FROM admin_messages am2
                WHERE am2.conversation_id = c.id
                  AND am2.sender_id = c.user_id
                  AND COALESCE(am2.is_read, 0) = 0
            ) AS unread_count
        """
        params = (int(limit), int(offset))
    else:
        unread_clause = """
            (
                SELECT COUNT(*)
                FROM admin_messages am2
                WHERE am2.conversation_id = c.id
                  AND am2.receiver_id = ?
                  AND COALESCE(am2.is_read, 0) = 0
            ) AS unread_count
        """
        params = (int(viewer_id), int(limit), int(offset))

    cursor.execute(
        f"""
        SELECT
            c.id,
            c.user_id,
            c.admin_id,
            c.last_message_at,
            c.created_at,
            c.updated_at,
            u.full_name AS user_name,
            u.email AS user_email,
            (
                SELECT am.content
                FROM admin_messages am
                WHERE am.conversation_id = c.id
                ORDER BY am.created_at DESC, am.id DESC
                LIMIT 1
            ) AS latest_message,
            {unread_clause}
        FROM admin_conversations c
        JOIN Users u ON u.id = c.user_id
        WHERE c.id = (
            SELECT c2.id
            FROM admin_conversations c2
            WHERE c2.user_id = c.user_id
            ORDER BY COALESCE(c2.last_message_at, c2.updated_at, c2.created_at) DESC, c2.created_at DESC
            LIMIT 1
        )
        ORDER BY {_conversation_sort_sql()}
        LIMIT ? OFFSET ?
        """,
        params,
    )
    rows = [_serialize_conversation(row) for row in cursor.fetchall()]
    return rows, total


def fetch_support_conversation(cursor, conversation_id, viewer_id, viewer_is_admin=False):
    if bool(viewer_is_admin):
        unread_clause = """
            (
                SELECT COUNT(*)
                FROM admin_messages am2
                WHERE am2.conversation_id = c.id
                  AND am2.sender_id = c.user_id
                  AND COALESCE(am2.is_read, 0) = 0
            ) AS unread_count
        """
        params = (str(conversation_id),)
    else:
        unread_clause = """
            (
                SELECT COUNT(*)
                FROM admin_messages am2
                WHERE am2.conversation_id = c.id
                  AND am2.receiver_id = ?
                  AND COALESCE(am2.is_read, 0) = 0
            ) AS unread_count
        """
        params = (int(viewer_id), str(conversation_id))

    cursor.execute(
        f"""
        SELECT
            c.id,
            c.user_id,
            c.admin_id,
            c.last_message_at,
            c.created_at,
            c.updated_at,
            u.full_name AS user_name,
            u.email AS user_email,
            (
                SELECT am.content
                FROM admin_messages am
                WHERE am.conversation_id = c.id
                ORDER BY am.created_at DESC, am.id DESC
                LIMIT 1
            ) AS latest_message,
            {unread_clause}
        FROM admin_conversations c
        JOIN Users u ON u.id = c.user_id
        WHERE c.id = ?
        LIMIT 1
        """,
        params,
    )
    row = cursor.fetchone()
    return _serialize_conversation(row) if row else None


def fetch_support_conversation_for_user(cursor, user_id, viewer_id):
    cursor.execute(
        f"""
        SELECT
            c.id,
            c.user_id,
            c.admin_id,
            c.last_message_at,
            c.created_at,
            c.updated_at,
            u.full_name AS user_name,
            u.email AS user_email,
            (
                SELECT am.content
                FROM admin_messages am
                WHERE am.conversation_id = c.id
                ORDER BY am.created_at DESC, am.id DESC
                LIMIT 1
            ) AS latest_message,
            (
                SELECT COUNT(*)
                FROM admin_messages am2
                WHERE am2.conversation_id = c.id
                  AND am2.receiver_id = ?
                  AND COALESCE(am2.is_read, 0) = 0
            ) AS unread_count
        FROM admin_conversations c
        JOIN Users u ON u.id = c.user_id
        WHERE c.user_id = ?
        ORDER BY {_conversation_sort_sql()}
        LIMIT 1
        """,
        (int(viewer_id), int(user_id)),
    )
    row = cursor.fetchone()
    return _serialize_conversation(row) if row else None


def fetch_support_messages(cursor, conversation_id, limit, offset):
    cursor.execute(
        "SELECT COUNT(*) AS total FROM admin_messages WHERE conversation_id = ?",
        (str(conversation_id),),
    )
    total = int(cursor.fetchone()["total"] or 0)

    cursor.execute(
        """
        SELECT
            am.id,
            am.conversation_id,
            am.sender_id,
            am.receiver_id,
            am.content,
            am.is_read,
            am.created_at,
            su.full_name AS sender_name,
            ru.full_name AS receiver_name
        FROM admin_messages am
        LEFT JOIN Users su ON su.id = am.sender_id
        LEFT JOIN Users ru ON ru.id = am.receiver_id
        WHERE am.conversation_id = ?
        ORDER BY am.created_at DESC, am.id DESC
        LIMIT ? OFFSET ?
        """,
        (str(conversation_id), int(limit), int(offset)),
    )
    rows = [_serialize_message(row) for row in cursor.fetchall()]
    return rows, total


def fetch_support_message(cursor, message_id):
    cursor.execute(
        """
        SELECT
            am.id,
            am.conversation_id,
            am.sender_id,
            am.receiver_id,
            am.content,
            am.is_read,
            am.created_at,
            su.full_name AS sender_name,
            ru.full_name AS receiver_name
        FROM admin_messages am
        LEFT JOIN Users su ON su.id = am.sender_id
        LEFT JOIN Users ru ON ru.id = am.receiver_id
        WHERE am.id = ?
        LIMIT 1
        """,
        (int(message_id),),
    )
    row = cursor.fetchone()
    return _serialize_message(row) if row else None
