from flask import Blueprint, g, jsonify, request

from database import db_connection
from decorators.rate_limit import rate_limit
from decorators.roles import admin_required
from extensions.socketio import (
    emit_conversation_new,
    emit_conversation_read,
    emit_conversation_updated,
    emit_message_new,
)
from routes.api_envelope import build_meta, parse_pagination
from routes.support_chat import (
    create_support_message,
    ensure_support_conversation,
    error_response,
    fetch_support_conversation,
    fetch_support_conversations,
    fetch_support_message,
    fetch_support_messages,
    get_conversation_owner_id,
    has_support_conversation_access,
    list_response,
    mark_messages_as_read_for_admin,
    single_response,
    touch_conversation,
    validate_message_content,
)


farms_admin_messages_api = Blueprint("farms_admin_messages_api", __name__)


def _admin_id():
    return int(g.current_user["id"])


@farms_admin_messages_api.route("/messages/conversations", methods=["GET"])
@admin_required
def admin_messages_conversations():
    page, per_page, offset = parse_pagination(request.args)
    admin_id = _admin_id()
    conn, cursor = db_connection()
    conversations, total = fetch_support_conversations(
        cursor,
        admin_id,
        per_page,
        offset,
        viewer_is_admin=True,
    )
    conn.close()
    meta = build_meta(page, per_page, total)
    return jsonify(list_response("conversations", conversations, "Conversations fetched", 200, meta)), 200


@farms_admin_messages_api.route("/messages/conversations", methods=["POST"])
@admin_required
def admin_messages_create_conversation():
    data = request.get_json() or {}
    raw_user_id = data.get("user_id")
    if raw_user_id is None:
        return jsonify(error_response("user_id is required", 400)), 400

    try:
        user_id = int(raw_user_id)
    except (TypeError, ValueError):
        return jsonify(error_response("user_id must be an integer", 400)), 400

    conn, cursor = db_connection()
    cursor.execute(
        """
        SELECT id, role, user_type, is_admin
        FROM Users
        WHERE id = ?
        LIMIT 1
        """,
        (user_id,),
    )
    user_row = cursor.fetchone()
    if not user_row:
        conn.close()
        return jsonify(error_response("User not found", 404)), 404

    role_value = str(user_row["role"] or user_row["user_type"] or "").strip().lower()
    if role_value == "admin" or bool(user_row["is_admin"]):
        conn.close()
        return jsonify(error_response("Cannot create support conversation for admin users", 400)), 400

    conversation_id, created = ensure_support_conversation(cursor, user_id, admin_id=_admin_id())
    conn.commit()
    conversation = fetch_support_conversation(cursor, conversation_id, _admin_id(), viewer_is_admin=True)
    conn.close()

    if created and conversation is not None:
        emit_conversation_new(conversation)
    if conversation is not None:
        emit_conversation_updated(conversation)

    status_code = 201 if created else 200
    status_message = "Conversation created" if created else "Conversation fetched"
    return jsonify(single_response("conversation", conversation, status_message, status_code)), status_code


@farms_admin_messages_api.route("/messages/conversations/<conv_id>", methods=["GET"])
@admin_required
def admin_messages_conversation_detail(conv_id):
    admin_id = _admin_id()
    conn, cursor = db_connection()
    conversation = fetch_support_conversation(cursor, conv_id, admin_id, viewer_is_admin=True)
    if conversation:
        cursor.execute(
            "SELECT COUNT(*) AS total FROM admin_messages WHERE conversation_id = ?",
            (str(conv_id),),
        )
        conversation["message_count"] = int(cursor.fetchone()["total"] or 0)
    conn.close()
    if not conversation:
        return jsonify(error_response("Conversation not found", 404)), 404
    return jsonify(single_response("conversation", conversation, "Conversation fetched", 200)), 200


@farms_admin_messages_api.route("/messages/conversations/<conv_id>/messages", methods=["GET"])
@admin_required
def admin_messages_list(conv_id):
    page, per_page, offset = parse_pagination(request.args)
    admin_id = _admin_id()
    conn, cursor = db_connection()
    if not has_support_conversation_access(cursor, conv_id, admin_id, is_admin=True):
        conn.close()
        return jsonify(error_response("Conversation not found", 404)), 404

    messages, total = fetch_support_messages(cursor, conv_id, per_page, offset)
    conn.close()
    meta = build_meta(page, per_page, total)
    return jsonify(list_response("messages", messages, "Messages fetched", 200, meta)), 200


@farms_admin_messages_api.route("/messages/conversations/<conv_id>/messages", methods=["POST"])
@admin_required
@rate_limit("admin-messages-send", limit=30, window_seconds=60)
def admin_messages_send(conv_id):
    data = request.get_json() or {}
    content, error = validate_message_content(data.get("content") or data.get("body"))
    if error:
        return jsonify(error_response(error, 400)), 400

    admin_id = _admin_id()
    conn, cursor = db_connection()
    if not has_support_conversation_access(cursor, conv_id, admin_id, is_admin=True):
        conn.close()
        return jsonify(error_response("Conversation not found", 404)), 404

    receiver_id = get_conversation_owner_id(cursor, conv_id)
    if receiver_id is None:
        conn.close()
        return jsonify(error_response("Conversation not found", 404)), 404

    message_id = create_support_message(cursor, conv_id, admin_id, receiver_id, content)
    touch_conversation(cursor, conv_id, admin_id=admin_id)
    conn.commit()

    conversation = fetch_support_conversation(cursor, conv_id, admin_id, viewer_is_admin=True)
    message = fetch_support_message(cursor, message_id)
    conn.close()

    if message is not None:
        emit_message_new(message, conversation=conversation)
    if conversation is not None:
        emit_conversation_updated(conversation)

    return jsonify(single_response("message", message, "Message sent", 201)), 201


@farms_admin_messages_api.route("/messages/conversations/<conv_id>/read", methods=["POST"])
@admin_required
def admin_messages_mark_read(conv_id):
    admin_id = _admin_id()
    conn, cursor = db_connection()
    if not has_support_conversation_access(cursor, conv_id, admin_id, is_admin=True):
        conn.close()
        return jsonify(error_response("Conversation not found", 404)), 404

    updated = mark_messages_as_read_for_admin(cursor, conv_id)
    conn.commit()
    conversation = fetch_support_conversation(cursor, conv_id, admin_id, viewer_is_admin=True)
    conn.close()

    emit_conversation_read(conv_id, admin_id, updated, conversation=conversation)
    if conversation is not None:
        emit_conversation_updated(conversation)

    payload = single_response("conversation", conversation, "Messages marked as read", 200)
    payload["updated"] = int(updated)
    return jsonify(payload), 200
