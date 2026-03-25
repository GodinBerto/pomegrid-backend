import json
import uuid


ALLOWED_ADMIN_NOTIFICATION_TYPES = {"order", "message", "system"}


def create_user_notification(cursor, user_id, notification_type, title, message, payload=None):
    cursor.execute(
        """
        INSERT INTO notifications (user_id, type, title, message, is_read, payload_json)
        VALUES (?, ?, ?, ?, 0, ?)
        """,
        (
            int(user_id),
            str(notification_type or "").strip().lower() or None,
            str(title or "").strip(),
            str(message or "").strip(),
            json.dumps(payload or {}),
        ),
    )
    return cursor.lastrowid


def create_admin_notification(cursor, notification_type, title, description=None, href=None):
    normalized_type = str(notification_type or "system").strip().lower()
    if normalized_type not in ALLOWED_ADMIN_NOTIFICATION_TYPES:
        normalized_type = "system"

    notification_id = str(uuid.uuid4())
    cursor.execute(
        """
        INSERT INTO admin_notifications (id, type, title, description, href, read)
        VALUES (?, ?, ?, ?, ?, 0)
        """,
        (
            notification_id,
            normalized_type,
            str(title or "").strip(),
            str(description or "").strip() or None,
            str(href or "").strip() or None,
        ),
    )
    return notification_id
