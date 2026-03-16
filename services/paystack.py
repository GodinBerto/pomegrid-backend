import hashlib
import hmac
import json
import urllib.error
import urllib.request
import uuid
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


DEFAULT_PAYSTACK_BASE_URL = "https://api.paystack.co"


class PaystackError(Exception):
    def __init__(self, message, status_code=502, payload=None):
        super().__init__(message)
        self.message = message
        self.status_code = int(status_code or 502)
        self.payload = payload


def generate_reference(prefix="pmgpay"):
    return f"{prefix}-{uuid.uuid4().hex[:16]}"


def amount_to_subunit(amount):
    try:
        normalized = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("amount must be a valid number") from exc

    if normalized <= 0:
        raise ValueError("amount must be greater than 0")

    return int(normalized * 100)


def subunit_to_amount(amount):
    try:
        normalized = Decimal(str(amount)) / Decimal("100")
    except (InvalidOperation, TypeError, ValueError):
        return 0.0
    return float(normalized.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def verify_webhook_signature(secret_key, payload, signature):
    if not secret_key or not signature:
        return False
    expected = hmac.new(secret_key.encode("utf-8"), payload, hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, signature)


def initialize_transaction(secret_key, email, amount, reference, callback_url=None, currency="GHS", metadata=None, base_url=None):
    payload = {
        "email": email,
        "amount": amount,
        "reference": reference,
        "currency": currency,
    }
    if callback_url:
        payload["callback_url"] = callback_url
    if metadata:
        payload["metadata"] = metadata
    response = _request(secret_key, "POST", "/transaction/initialize", payload=payload, base_url=base_url)
    return response.get("data") or {}


def verify_transaction(secret_key, reference, base_url=None):
    response = _request(secret_key, "GET", f"/transaction/verify/{reference}", base_url=base_url)
    return response.get("data") or {}


def _request(secret_key, method, path, payload=None, base_url=None):
    if not secret_key:
        raise PaystackError("Paystack secret key is not configured", 503)

    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")

    request = urllib.request.Request(
        _build_url(base_url, path),
        data=data,
        method=method.upper(),
        headers={
            "Authorization": f"Bearer {secret_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            parsed = _decode_response_body(response.read())
    except urllib.error.HTTPError as exc:
        parsed = _decode_response_body(exc.read())
        message = parsed.get("message") or "Paystack request failed"
        raise PaystackError(message, exc.code, parsed) from exc
    except urllib.error.URLError as exc:
        raise PaystackError("Unable to reach Paystack", 502) from exc

    if not parsed.get("status"):
        raise PaystackError(parsed.get("message") or "Paystack request failed", 502, parsed)

    return parsed


def _build_url(base_url, path):
    normalized_base = str(base_url or DEFAULT_PAYSTACK_BASE_URL).strip().rstrip("/")
    return f"{normalized_base}{path}"


def _decode_response_body(body):
    if not body:
        return {}
    text = body.decode("utf-8", errors="replace")
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}
