import importlib.util
import logging
import os

from flask import request, session
from flask_jwt_extended import decode_token
from flask_socketio import SocketIO, emit, join_room, leave_room

from database import db_connection
from decorators.roles import normalize_role


logger = logging.getLogger(__name__)

ROOM_ADMINS = "admins"
ROOM_CONVERSATION_PREFIX = "conversation:"


def _resolve_async_mode():
    configured_mode = str(os.getenv("SOCKETIO_ASYNC_MODE") or "").strip().lower()
    if configured_mode:
        return configured_mode
    if importlib.util.find_spec("gevent") is not None:
        return "gevent"
    return "threading"


socketio = SocketIO(
    cors_allowed_origins="*",
    async_mode=_resolve_async_mode(),
    manage_session=True,
)


def conversation_room(conversation_id):
    return f"{ROOM_CONVERSATION_PREFIX}{conversation_id}"


def _extract_access_token(auth_payload):
    if isinstance(auth_payload, dict):
        for key in ("token", "access_token", "jwt"):
            token = str(auth_payload.get(key) or "").strip()
            if token:
                return token

    auth_header = str(request.headers.get("Authorization") or "").strip()
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()

    for key in ("token", "access_token", "jwt"):
        token = str(request.args.get(key) or "").strip()
        if token:
            return token

    cookie_token = str(request.cookies.get("access_token_cookie") or "").strip()
    if cookie_token:
        return cookie_token

    return None


def _load_active_user(user_id):
    conn, cursor = db_connection()
    cursor.execute(
        """
        SELECT id, full_name, role, user_type, is_admin, is_active, status
        FROM Users
        WHERE id = ?
        LIMIT 1
        """,
        (int(user_id),),
    )
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None

    status = str(row["status"] or "").strip().lower()
    if not bool(row["is_active"]) or status not in {"", "active"}:
        return None

    normalized_role = normalize_role(row["role"] or row["user_type"], row["is_admin"])
    return {
        "id": int(row["id"]),
        "full_name": row["full_name"],
        "role": normalized_role,
        "is_admin": normalized_role == "admin",
    }


def _authenticate_socket_user(auth_payload):
    token = _extract_access_token(auth_payload)
    if token:
        try:
            decoded = decode_token(token)
        except Exception:
            return None

        identity = decoded.get("sub")
        if identity is None:
            return None

        try:
            user_id = int(str(identity).strip())
        except (TypeError, ValueError):
            return None

        return _load_active_user(user_id)

    # Session fallback for deployments that store authenticated user id in session.
    for key in ("user_id", "id"):
        raw_user_id = session.get(key)
        if raw_user_id is None:
            continue
        try:
            return _load_active_user(int(raw_user_id))
        except (TypeError, ValueError):
            continue
    return None


def _get_socket_user():
    user_id = session.get("socket_user_id")
    role = session.get("socket_user_role")
    is_admin = bool(session.get("socket_user_is_admin"))
    if user_id is None:
        return None
    try:
        return {
            "id": int(user_id),
            "role": str(role or "user"),
            "is_admin": bool(is_admin),
        }
    except (TypeError, ValueError):
        return None


def _can_access_conversation(user, conversation_id):
    conn, cursor = db_connection()
    if bool(user["is_admin"]):
        cursor.execute(
            "SELECT 1 FROM admin_conversations WHERE id = ?",
            (str(conversation_id),),
        )
    else:
        cursor.execute(
            """
            SELECT 1
            FROM admin_conversations
            WHERE id = ? AND user_id = ?
            """,
            (str(conversation_id), int(user["id"])),
        )
    row = cursor.fetchone()
    conn.close()
    return row is not None


def register_socket_handlers():
    @socketio.on("connect")
    def handle_connect(auth=None):
        user = _authenticate_socket_user(auth)
        if not user:
            logger.warning(
                "Socket connection rejected: origin=%s has_token=%s transport=%s",
                request.headers.get("Origin"),
                bool(_extract_access_token(auth)),
                request.args.get("transport"),
            )
            return False

        session["socket_user_id"] = int(user["id"])
        session["socket_user_role"] = user["role"]
        session["socket_user_is_admin"] = bool(user["is_admin"])

        if bool(user["is_admin"]):
            join_room(ROOM_ADMINS)
        else:
            conn, cursor = db_connection()
            cursor.execute(
                """
                SELECT id
                FROM admin_conversations
                WHERE user_id = ?
                ORDER BY COALESCE(last_message_at, updated_at, created_at) DESC, created_at DESC
                LIMIT 1
                """,
                (int(user["id"]),),
            )
            row = cursor.fetchone()
            conn.close()
            if row:
                join_room(conversation_room(row["id"]))

    @socketio.on("conversation:join")
    def handle_conversation_join(data):
        user = _get_socket_user()
        if not user:
            emit("socket:error", {"message": "Unauthorized"})
            return

        payload = data if isinstance(data, dict) else {}
        conversation_id = str(payload.get("conversation_id") or "").strip()
        if not conversation_id:
            emit("socket:error", {"message": "conversation_id is required"})
            return

        if not _can_access_conversation(user, conversation_id):
            emit("socket:error", {"message": "Forbidden"})
            return

        join_room(conversation_room(conversation_id))
        emit("conversation:joined", {"conversation_id": conversation_id})

    @socketio.on("conversation:leave")
    def handle_conversation_leave(data):
        payload = data if isinstance(data, dict) else {}
        conversation_id = str(payload.get("conversation_id") or "").strip()
        if not conversation_id:
            emit("socket:error", {"message": "conversation_id is required"})
            return
        leave_room(conversation_room(conversation_id))
        emit("conversation:left", {"conversation_id": conversation_id})


def emit_conversation_new(conversation):
    payload = {"conversation": conversation}
    room = conversation_room(conversation["id"])
    socketio.emit("conversation:new", payload, room=ROOM_ADMINS)
    socketio.emit("conversation:new", payload, room=room)


def emit_conversation_updated(conversation):
    payload = {"conversation": conversation}
    room = conversation_room(conversation["id"])
    socketio.emit("conversation:updated", payload, room=ROOM_ADMINS)
    socketio.emit("conversation:updated", payload, room=room)


def emit_message_new(message, conversation=None):
    payload = {"message": message}
    if conversation is not None:
        payload["conversation"] = conversation
    room = conversation_room(message["conversation_id"])
    socketio.emit("message:new", payload, room=ROOM_ADMINS)
    socketio.emit("message:new", payload, room=room)


def emit_conversation_read(conversation_id, reader_id, updated, conversation=None):
    payload = {
        "conversation_id": str(conversation_id),
        "reader_id": int(reader_id),
        "updated": int(updated),
    }
    if conversation is not None:
        payload["conversation"] = conversation
    room = conversation_room(conversation_id)
    socketio.emit("conversation:read", payload, room=ROOM_ADMINS)
    socketio.emit("conversation:read", payload, room=room)
