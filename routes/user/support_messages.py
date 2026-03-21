from flask import Blueprint, g, jsonify, request

from database import db_connection
from decorators.rate_limit import rate_limit
from decorators.roles import ROLE_USER, ROLE_WORKER
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
    fetch_support_conversation_for_user,
    fetch_support_message,
    fetch_support_messages,
    get_active_admin_id,
    get_support_conversation_id_for_user,
    list_response,
    mark_messages_as_read,
    single_response,
    touch_conversation,
    validate_message_content,
)
from routes.middleware import protect_blueprint


user_support_api = Blueprint("user_support_api", __name__)
protect_blueprint(user_support_api, ROLE_USER, ROLE_WORKER)


def _current_user_id():
    return int(g.current_user["id"])


@user_support_api.route("/messages/support/conversation", methods=["GET"])
def user_support_conversation_get():
    user_id = _current_user_id()
    conn, cursor = db_connection()
    conversation = fetch_support_conversation_for_user(cursor, user_id, user_id)
    conn.close()
    return jsonify(single_response("conversation", conversation, "Conversation fetched", 200)), 200


@user_support_api.route("/messages/support/conversation/messages", methods=["GET"])
def user_support_messages_get():
    page, per_page, offset = parse_pagination(request.args)
    user_id = _current_user_id()

    conn, cursor = db_connection()
    conversation_id = get_support_conversation_id_for_user(cursor, user_id)
    if not conversation_id:
        conn.close()
        meta = build_meta(page, per_page, 0)
        return jsonify(list_response("messages", [], "Messages fetched", 200, meta)), 200

    messages, total = fetch_support_messages(cursor, conversation_id, per_page, offset)
    conn.close()
    meta = build_meta(page, per_page, total)
    return jsonify(list_response("messages", messages, "Messages fetched", 200, meta)), 200


@user_support_api.route("/messages/support/conversation/messages", methods=["POST"])
@rate_limit("user-support-message-send", limit=30, window_seconds=60)
def user_support_messages_send():
    data = request.get_json() or {}
    content, error = validate_message_content(data.get("content") or data.get("body"))
    if error:
        return jsonify(error_response(error, 400)), 400

    user_id = _current_user_id()
    conn, cursor = db_connection()
    conversation_id, created = ensure_support_conversation(cursor, user_id)

    conversation = fetch_support_conversation(cursor, conversation_id, user_id)
    receiver_admin_id = conversation["admin_id"] if conversation and conversation["admin_id"] is not None else None
    if receiver_admin_id is None:
        receiver_admin_id = get_active_admin_id(cursor)
    if receiver_admin_id is None:
        conn.rollback()
        conn.close()
        return jsonify(error_response("No active admin support agent available", 503)), 503

    message_id = create_support_message(cursor, conversation_id, user_id, receiver_admin_id, content)
    touch_conversation(cursor, conversation_id, admin_id=receiver_admin_id)
    conn.commit()

    conversation = fetch_support_conversation(cursor, conversation_id, user_id)
    message = fetch_support_message(cursor, message_id)
    conn.close()

    if created and conversation is not None:
        emit_conversation_new(conversation)
    if message is not None:
        emit_message_new(message, conversation=conversation)
    if conversation is not None:
        emit_conversation_updated(conversation)

    return jsonify(single_response("message", message, "Message sent", 201)), 201


@user_support_api.route("/messages/support/conversation/read", methods=["POST"])
def user_support_mark_read():
    user_id = _current_user_id()
    conn, cursor = db_connection()
    conversation_id = get_support_conversation_id_for_user(cursor, user_id)
    if not conversation_id:
        conn.close()
        payload = single_response("conversation", None, "Messages marked as read", 200)
        payload["updated"] = 0
        return jsonify(payload), 200

    updated = mark_messages_as_read(cursor, conversation_id, user_id)
    conn.commit()
    conversation = fetch_support_conversation(cursor, conversation_id, user_id)
    conn.close()

    emit_conversation_read(conversation_id, user_id, updated, conversation=conversation)
    if conversation is not None:
        emit_conversation_updated(conversation)

    payload = single_response("conversation", conversation, "Messages marked as read", 200)
    payload["updated"] = int(updated)
    return jsonify(payload), 200
