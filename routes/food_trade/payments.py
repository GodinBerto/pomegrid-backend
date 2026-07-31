import json
import logging
from flask import current_app, jsonify, request
from flask_jwt_extended import jwt_required

from database import db_connection
from middleware.authMiddleware import get_authenticated_user_id
from routes.api_envelope import build_meta, envelope, parse_pagination
from services.paystack import (
    PaystackError,
    amount_to_subunit,
    generate_reference,
    initialize_transaction,
    parse_subunit_amount,
    subunit_to_amount,
    verify_transaction,
    verify_webhook_signature,
)
from . import food_trade_api
from .utils import check_admin

logger = logging.getLogger(__name__)

PAYMENT_SELECT = """
    SELECT
        p.id,
        p.user_id,
        p.provider,
        p.reference,
        p.access_code,
        p.authorization_url,
        p.amount,
        p.currency,
        p.status,
        p.gateway_response,
        p.gateway_payload_json,
        p.channel,
        p.customer_email,
        p.metadata_json,
        p.paid_at,
        p.created_at,
        p.updated_at
    FROM food_trade_payments p
"""

def _safe_json_loads(value, default=None):
    fallback = {} if default is None else default
    if value in (None, ""):
        return fallback
    try:
        return json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback

def _safe_json_dumps(value):
    if value in (None, "", {}, []):
        return None
    return json.dumps(value)

def _normalize_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
    return None

def _serialize_payment_row(row, include_gateway_payload=False):
    payment = dict(row)
    payment["amount"] = float(payment.get("amount") or 0)
    payment["metadata"] = _safe_json_loads(payment.pop("metadata_json", None), {})
    gateway_payload = _safe_json_loads(payment.pop("gateway_payload_json", None), {})
    if include_gateway_payload:
        payment["gateway_payload"] = gateway_payload
    return payment

def _fetch_payment_by_reference(cursor, reference):
    cursor.execute(
        f"{PAYMENT_SELECT} WHERE p.reference = ?",
        (reference,),
    )
    return cursor.fetchone()

def _payment_access_allowed(payment_row, user_id):
    if check_admin(user_id):
        return True
    return int(payment_row["user_id"]) == int(user_id)

def _build_reference(cursor, provided_reference=None):
    if provided_reference:
        cursor.execute("SELECT id FROM food_trade_payments WHERE reference = ?", (provided_reference,))
        if cursor.fetchone():
            raise ValueError("Payment reference already exists")
        return provided_reference

    reference = generate_reference("pmgft")
    while True:
        cursor.execute("SELECT id FROM food_trade_payments WHERE reference = ?", (reference,))
        if not cursor.fetchone():
            return reference
        reference = generate_reference("pmgft")

def _resolve_initialize_amount(data):
    if data.get("amount_subunit") not in (None, ""):
        amount_subunit = parse_subunit_amount(data.get("amount_subunit"))
        return amount_subunit, subunit_to_amount(amount_subunit)

    amount_mode = _normalize_bool(data.get("amount_in_subunit"))
    if amount_mode is False:
        amount_subunit = amount_to_subunit(data.get("amount"))
    else:
        amount_subunit = parse_subunit_amount(data.get("amount"))
    return amount_subunit, subunit_to_amount(amount_subunit)

def _merge_metadata(existing_metadata_json, incoming_metadata):
    merged = _safe_json_loads(existing_metadata_json, {})
    if isinstance(incoming_metadata, dict):
        merged.update(incoming_metadata)
    return _safe_json_dumps(merged)

def _update_payment_from_gateway(cursor, payment_row, transaction_data):
    gateway_status = str(transaction_data.get("status") or payment_row["status"] or "pending").strip().lower()
    raw_amount = transaction_data.get("amount")
    amount = subunit_to_amount(raw_amount) if raw_amount is not None else float(payment_row["amount"] or 0)
    currency = str(transaction_data.get("currency") or payment_row["currency"] or "").strip().upper()
    gateway_response = str(transaction_data.get("gateway_response") or payment_row["gateway_response"] or "").strip() or None
    channel = str(transaction_data.get("channel") or payment_row["channel"] or "").strip() or None
    paid_at = transaction_data.get("paid_at") or payment_row["paid_at"]
    customer = transaction_data.get("customer") if isinstance(transaction_data.get("customer"), dict) else {}
    customer_email = str(customer.get("email") or payment_row["customer_email"] or "").strip() or None
    metadata_json = _merge_metadata(payment_row["metadata_json"], transaction_data.get("metadata"))

    cursor.execute(
        """
        UPDATE food_trade_payments
        SET
            amount = ?,
            currency = ?,
            status = ?,
            gateway_response = ?,
            gateway_payload_json = ?,
            channel = ?,
            customer_email = ?,
            metadata_json = ?,
            paid_at = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            amount,
            currency,
            gateway_status,
            gateway_response,
            _safe_json_dumps(transaction_data),
            channel,
            customer_email,
            metadata_json,
            paid_at,
            payment_row["id"],
        ),
    )

def _create_gateway_payment_if_missing(cursor, reference, transaction_data):
    metadata = transaction_data.get("metadata") if isinstance(transaction_data.get("metadata"), dict) else {}
    user_id = metadata.get("user_id")
    if user_id in (None, ""):
        return None

    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return None

    customer = transaction_data.get("customer") if isinstance(transaction_data.get("customer"), dict) else {}
    cursor.execute(
        """
        INSERT INTO food_trade_payments (
            user_id,
            provider,
            reference,
            amount,
            currency,
            status,
            gateway_response,
            gateway_payload_json,
            channel,
            customer_email,
            metadata_json,
            paid_at
        )
        VALUES (?, 'paystack', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            reference,
            subunit_to_amount(transaction_data.get("amount")),
            str(transaction_data.get("currency") or "").strip().upper(),
            str(transaction_data.get("status") or "pending").strip().lower(),
            str(transaction_data.get("gateway_response") or "").strip() or None,
            _safe_json_dumps(transaction_data),
            str(transaction_data.get("channel") or "").strip() or None,
            str(customer.get("email") or "").strip() or None,
            _safe_json_dumps(metadata),
            transaction_data.get("paid_at"),
        ),
    )

    cursor.execute(
        f"{PAYMENT_SELECT} WHERE p.id = ?",
        (cursor.lastrowid,),
    )
    return cursor.fetchone()


@food_trade_api.route("/payments", methods=["GET"])
@food_trade_api.route("/payments/", methods=["GET"])
@jwt_required()
def list_payments():
    user_id = get_authenticated_user_id()
    if user_id is None:
        return jsonify(envelope(None, "Invalid token identity", 401, False)), 401

    page, per_page, offset = parse_pagination(request.args)
    status = str(request.args.get("status") or "").strip().lower()
    reference = str(request.args.get("reference") or "").strip()

    where = ["p.user_id = ?"]
    params = [user_id]

    if status:
        where.append("LOWER(COALESCE(p.status, '')) = ?")
        params.append(status)

    if reference:
        where.append("LOWER(COALESCE(p.reference, '')) LIKE LOWER(?)")
        params.append(f"%{reference}%")

    where_sql = " AND ".join(where)

    try:
        conn, cursor = db_connection()
        cursor.execute(f"SELECT COUNT(*) AS total FROM food_trade_payments p WHERE {where_sql}", tuple(params))
        total = int(cursor.fetchone()["total"] or 0)

        query_params = list(params) + [per_page, offset]
        cursor.execute(
            f"""
            {PAYMENT_SELECT}
            WHERE {where_sql}
            ORDER BY p.created_at DESC, p.id DESC
            LIMIT ? OFFSET ?
            """,
            tuple(query_params),
        )
        rows = [_serialize_payment_row(row) for row in cursor.fetchall()]
        conn.close()

        meta = build_meta(page, per_page, total)
        return jsonify(envelope(rows, "Payments fetched", 200, True, meta)), 200
    except Exception as exc:
        logger.exception("Failed to list food trade payments")
        return jsonify(envelope(None, f"Error: {exc}", 500, False)), 500


@food_trade_api.route("/payments/initialize", methods=["POST"])
@jwt_required()
def initialize_payment():
    user_id = get_authenticated_user_id()
    if user_id is None:
        return jsonify(envelope(None, "Invalid token identity", 401, False)), 401

    data = request.get_json(silent=True) or {}
    callback_url = str(data.get("callback_url") or current_app.config.get("PAYSTACK_CALLBACK_URL") or "").strip() or None
    currency = str(data.get("currency") or "").strip().upper() or None
    provided_reference = str(data.get("reference") or "").strip() or None
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}

    if data.get("metadata") not in (None, {}) and not isinstance(data.get("metadata"), dict):
        return jsonify(envelope(None, "metadata must be an object", 400, False)), 400

    conn = None
    try:
        conn, cursor = db_connection()
        cursor.execute("SELECT id, email, full_name FROM Users WHERE id = ?", (user_id,))
        user_row = cursor.fetchone()
        if not user_row:
            conn.close()
            return jsonify(envelope(None, "User not found", 404, False)), 404

        email = str(data.get("email") or user_row["email"] or "").strip().lower()
        if not email:
            conn.close()
            return jsonify(envelope(None, "A customer email is required", 400, False)), 400

        amount_subunit, amount = _resolve_initialize_amount(data)
        reference = _build_reference(cursor, provided_reference)

        metadata_payload = dict(metadata)
        metadata_payload.update(
            {
                "user_id": user_id,
                "reference": reference,
            }
        )

        try:
            metadata_json = _safe_json_dumps(metadata_payload)
        except TypeError:
            conn.close()
            return jsonify(envelope(None, "metadata must be JSON serializable", 400, False)), 400

        paystack_data = initialize_transaction(
            current_app.config.get("PAYSTACK_SECRET_KEY"),
            email=email,
            amount=amount_subunit,
            reference=reference,
            callback_url=callback_url,
            currency=currency,
            metadata=metadata_payload,
            base_url=current_app.config.get("PAYSTACK_BASE_URL"),
        )
        gateway_reference = str(paystack_data.get("reference") or reference).strip() or reference

        cursor.execute(
            """
            INSERT INTO food_trade_payments (
                user_id,
                provider,
                reference,
                access_code,
                authorization_url,
                amount,
                currency,
                status,
                gateway_response,
                gateway_payload_json,
                customer_email,
                metadata_json
            )
            VALUES (?, 'paystack', ?, ?, ?, ?, ?, 'initialized', ?, ?, ?, ?)
            """,
            (
                user_id,
                gateway_reference,
                paystack_data.get("access_code"),
                paystack_data.get("authorization_url"),
                amount,
                currency or "",
                "Authorization URL created",
                _safe_json_dumps(paystack_data),
                email,
                metadata_json,
            ),
        )

        payment_id = cursor.lastrowid
        conn.commit()
        
        cursor.execute(f"{PAYMENT_SELECT} WHERE p.id = ?", (payment_id,))
        payment_payload = _serialize_payment_row(cursor.fetchone(), include_gateway_payload=True)
        payload = {
            "authorization_url": paystack_data.get("authorization_url"),
            "access_code": paystack_data.get("access_code"),
            "reference": gateway_reference,
            "payment": payment_payload,
        }
        conn.close()
        return jsonify(envelope(payload, "Authorization URL created", 200)), 200
    except ValueError as exc:
        if conn is not None:
            conn.close()
        return jsonify(envelope(None, str(exc), 400, False)), 400
    except PaystackError as exc:
        if conn is not None:
            conn.close()
        return jsonify(envelope(exc.payload, exc.message, exc.status_code, False)), exc.status_code
    except Exception as exc:
        if conn is not None:
            conn.close()
        logger.exception("Failed to initialize payment")
        return jsonify(envelope(None, f"Error: {exc}", 500, False)), 500


@food_trade_api.route("/payments/verify/<reference>", methods=["GET"])
@jwt_required()
def verify_payment(reference):
    user_id = get_authenticated_user_id()
    if user_id is None:
        return jsonify(envelope(None, "Invalid token identity", 401, False)), 401

    conn = None
    try:
        conn, cursor = db_connection()
        payment_row = _fetch_payment_by_reference(cursor, reference)
        if not payment_row:
            conn.close()
            return jsonify(envelope(None, "Payment not found", 404, False)), 404

        if not _payment_access_allowed(payment_row, user_id):
            conn.close()
            return jsonify(envelope(None, "Forbidden", 403, False)), 403

        transaction_data = verify_transaction(
            current_app.config.get("PAYSTACK_SECRET_KEY"),
            reference=reference,
            base_url=current_app.config.get("PAYSTACK_BASE_URL"),
        )
        _update_payment_from_gateway(cursor, payment_row, transaction_data)
        conn.commit()
        
        updated_row = _fetch_payment_by_reference(cursor, reference)
        payload = _serialize_payment_row(updated_row, include_gateway_payload=True)
        conn.close()
        return jsonify(envelope(payload, "Payment verified", 200)), 200
    except PaystackError as exc:
        if conn is not None:
            conn.close()
        return jsonify(envelope(exc.payload, exc.message, exc.status_code, False)), exc.status_code
    except Exception as exc:
        if conn is not None:
            conn.close()
        logger.exception("Failed to verify payment %s", reference)
        return jsonify(envelope(None, f"Error: {exc}", 500, False)), 500


@food_trade_api.route("/payments/webhook", methods=["POST"])
def paystack_webhook():
    secret_key = current_app.config.get("PAYSTACK_SECRET_KEY")
    raw_payload = request.get_data(cache=True)
    signature = request.headers.get("X-Paystack-Signature", "")

    if not verify_webhook_signature(secret_key, raw_payload, signature):
        return jsonify(envelope(None, "Invalid Paystack signature", 401, False)), 401

    event_payload = request.get_json(silent=True) or {}
    event_type = str(event_payload.get("event") or "").strip().lower()
    transaction_data = event_payload.get("data") if isinstance(event_payload.get("data"), dict) else {}
    reference = str(transaction_data.get("reference") or "").strip()

    if not reference or not event_type.startswith("charge."):
        return jsonify(envelope({"received": True}, "Webhook received", 200)), 200

    conn = None
    try:
        conn, cursor = db_connection()
        payment_row = _fetch_payment_by_reference(cursor, reference)
        if not payment_row:
            payment_row = _create_gateway_payment_if_missing(cursor, reference, transaction_data)

        if payment_row:
            _update_payment_from_gateway(cursor, payment_row, transaction_data)
            conn.commit()

        if conn is not None:
            conn.close()
        return jsonify(envelope({"received": True, "reference": reference}, "Webhook processed", 200)), 200
    except Exception as exc:
        if conn is not None:
            conn.close()
        logger.exception("Failed to process Paystack webhook")
        return jsonify(envelope(None, f"Error: {exc}", 500, False)), 500


@food_trade_api.route("/payments/<reference>", methods=["GET"])
@jwt_required()
def get_payment(reference):
    user_id = get_authenticated_user_id()
    if user_id is None:
        return jsonify(envelope(None, "Invalid token identity", 401, False)), 401

    try:
        conn, cursor = db_connection()
        payment_row = _fetch_payment_by_reference(cursor, reference)
        conn.close()
        if not payment_row:
            return jsonify(envelope(None, "Payment not found", 404, False)), 404
        if not _payment_access_allowed(payment_row, user_id):
            return jsonify(envelope(None, "Forbidden", 403, False)), 403
            
        return jsonify(envelope(_serialize_payment_row(payment_row, include_gateway_payload=True), "Payment fetched", 200)), 200
    except Exception as exc:
        logger.exception("Failed to fetch payment %s", reference)
        return jsonify(envelope(None, f"Error: {exc}", 500, False)), 500
