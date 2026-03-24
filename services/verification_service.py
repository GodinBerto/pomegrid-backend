import base64
import json
import logging
import smtplib
from email.message import EmailMessage
from secrets import randbelow
from urllib import parse as urllib_parse
from urllib import error as urllib_error
from urllib import request as urllib_request

from config import Config


logger = logging.getLogger(__name__)
SUPPORTED_VERIFICATION_CHANNELS = {"email", "phone"}


def generate_verification_code(length=6):
    if length < 4:
        length = 4
    return f"{randbelow(10 ** length):0{length}d}"


def normalize_verification_channel(channel, default="email"):
    normalized = str(channel or default).strip().lower()
    aliases = {
        "sms": "phone",
        "mobile": "phone",
        "telephone": "phone",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in SUPPORTED_VERIFICATION_CHANNELS:
        raise ValueError("verification_channel must be email or phone")
    return normalized


def validate_verification_target(channel, email=None, phone=None):
    normalized_channel = normalize_verification_channel(channel)
    if normalized_channel == "phone":
        target = sanitize_phone_target(phone)
        digits = "".join(ch for ch in target if ch.isdigit())
        if len(digits) < 10:
            raise ValueError("A valid phone number is required for phone verification")
        return normalized_channel, target

    target = str(email or "").strip().lower()
    if "@" not in target:
        raise ValueError("A valid email address is required for email verification")
    return "email", target


def mask_verification_target(channel, target):
    value = str(target or "").strip()
    if not value:
        return ""

    if channel == "phone":
        visible = value[-4:] if len(value) >= 4 else value
        return f"{'*' * max(len(value) - len(visible), 0)}{visible}"

    if "@" not in value:
        return value

    local, domain = value.split("@", 1)
    if len(local) <= 2:
        masked_local = f"{local[:1]}*"
    else:
        masked_local = f"{local[:2]}{'*' * max(len(local) - 2, 1)}"
    return f"{masked_local}@{domain}"


def sanitize_phone_target(target):
    raw_value = str(target or "").strip()
    if not raw_value:
        return ""

    digits = "".join(ch for ch in raw_value if ch.isdigit())
    if raw_value.startswith("+"):
        return f"+{digits}"
    return digits


def deliver_verification_code(channel, target, code, expiry_minutes):
    normalized_channel = normalize_verification_channel(channel)
    if normalized_channel == "phone":
        return _send_phone_code(target, code, expiry_minutes)
    return _send_email_code(target, code, expiry_minutes)


def _send_email_code(target, code, expiry_minutes):
    smtp_host = str(Config.SMTP_HOST or "").strip()
    from_email = str(Config.SMTP_FROM_EMAIL or Config.SMTP_USERNAME or "").strip()
    if not smtp_host or not from_email:
        return _fallback_delivery("email", target, code, "SMTP delivery is not configured")

    message = EmailMessage()
    sender_name = str(Config.SMTP_FROM_NAME or "").strip()
    if sender_name:
        message["From"] = f"{sender_name} <{from_email}>"
    else:
        message["From"] = from_email
    message["To"] = target
    message["Subject"] = Config.VERIFICATION_EMAIL_SUBJECT
    message.set_content(
        (
            "Your Pomegrid verification code is "
            f"{code}. It expires in {int(expiry_minutes)} minutes."
        )
    )

    try:
        if Config.SMTP_USE_SSL:
            smtp_client = smtplib.SMTP_SSL(smtp_host, Config.SMTP_PORT, timeout=15)
        else:
            smtp_client = smtplib.SMTP(smtp_host, Config.SMTP_PORT, timeout=15)

        with smtp_client as server:
            if Config.SMTP_USE_TLS and not Config.SMTP_USE_SSL:
                server.starttls()
            if Config.SMTP_USERNAME:
                server.login(Config.SMTP_USERNAME, Config.SMTP_PASSWORD)
            server.send_message(message)
    except Exception as exc:
        logger.exception("Failed to send verification email to %s", target)
        return _fallback_delivery("email", target, code, str(exc))

    return {
        "channel": "email",
        "target": target,
        "masked_target": mask_verification_target("email", target),
        "delivery_method": "smtp",
        "delivered": True,
    }


def _send_phone_code(target, code, expiry_minutes):
    twilio_sid = str(Config.TWILIO_ACCOUNT_SID or "").strip()
    twilio_token = str(Config.TWILIO_AUTH_TOKEN or "").strip()
    twilio_from_phone = str(Config.TWILIO_FROM_PHONE or "").strip()
    twilio_messaging_service_sid = str(Config.TWILIO_MESSAGING_SERVICE_SID or "").strip()

    if twilio_sid and twilio_token and (twilio_from_phone or twilio_messaging_service_sid):
        return _send_phone_code_via_twilio(target, code, expiry_minutes)

    webhook_url = str(Config.SMS_WEBHOOK_URL or "").strip()
    if not webhook_url:
        return _fallback_delivery(
            "phone",
            target,
            code,
            "SMS delivery is not configured. Provide Twilio credentials or SMS_WEBHOOK_URL.",
        )

    payload = {
        "to": target,
        "message": f"Your Pomegrid verification code is {code}. It expires in {int(expiry_minutes)} minutes.",
        "code": code,
        "sender_id": str(Config.SMS_SENDER_ID or "Pomegrid").strip(),
    }
    headers = {
        "Content-Type": "application/json",
    }
    if Config.SMS_WEBHOOK_TOKEN:
        headers["Authorization"] = f"Bearer {Config.SMS_WEBHOOK_TOKEN}"

    request = urllib_request.Request(
        webhook_url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib_request.urlopen(request, timeout=15) as response:
            status_code = int(getattr(response, "status", response.getcode()))
    except urllib_error.HTTPError as exc:
        logger.exception("SMS webhook returned error while sending to %s", target)
        return _fallback_delivery("phone", target, code, f"SMS webhook HTTP {exc.code}")
    except Exception as exc:
        logger.exception("Failed to send verification SMS to %s", target)
        return _fallback_delivery("phone", target, code, str(exc))

    if status_code < 200 or status_code >= 300:
        return _fallback_delivery("phone", target, code, f"SMS webhook HTTP {status_code}")

    return {
        "channel": "phone",
        "target": target,
        "masked_target": mask_verification_target("phone", target),
        "delivery_method": "sms_webhook",
        "delivered": True,
    }


def _send_phone_code_via_twilio(target, code, expiry_minutes):
    sanitized_target = sanitize_phone_target(target)
    body = f"Your Pomegrid verification code is {code}. It expires in {int(expiry_minutes)} minutes."
    payload = {
        "To": sanitized_target,
        "Body": body,
    }

    messaging_service_sid = str(Config.TWILIO_MESSAGING_SERVICE_SID or "").strip()
    from_phone = str(Config.TWILIO_FROM_PHONE or "").strip()
    if messaging_service_sid:
        payload["MessagingServiceSid"] = messaging_service_sid
    elif from_phone:
        payload["From"] = sanitize_phone_target(from_phone)
    else:
        return _fallback_delivery(
            "phone",
            target,
            code,
            "Twilio is configured but no TWILIO_FROM_PHONE or TWILIO_MESSAGING_SERVICE_SID was provided.",
        )

    account_sid = str(Config.TWILIO_ACCOUNT_SID or "").strip()
    auth_token = str(Config.TWILIO_AUTH_TOKEN or "").strip()
    auth_value = base64.b64encode(f"{account_sid}:{auth_token}".encode("utf-8")).decode("ascii")
    request = urllib_request.Request(
        f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json",
        data=urllib_parse.urlencode(payload).encode("utf-8"),
        headers={
            "Authorization": f"Basic {auth_value}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )

    try:
        with urllib_request.urlopen(request, timeout=15) as response:
            status_code = int(getattr(response, "status", response.getcode()))
            response_body = response.read().decode("utf-8", errors="ignore")
    except urllib_error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="ignore")
        logger.exception("Twilio SMS returned error while sending to %s: %s", sanitized_target, error_body)
        return _fallback_delivery("phone", target, code, f"Twilio SMS HTTP {exc.code}")
    except Exception as exc:
        logger.exception("Failed to send Twilio verification SMS to %s", sanitized_target)
        return _fallback_delivery("phone", target, code, str(exc))

    if status_code < 200 or status_code >= 300:
        logger.warning("Unexpected Twilio SMS response for %s: %s %s", sanitized_target, status_code, response_body)
        return _fallback_delivery("phone", target, code, f"Twilio SMS HTTP {status_code}")

    return {
        "channel": "phone",
        "target": sanitized_target,
        "masked_target": mask_verification_target("phone", sanitized_target),
        "delivery_method": "twilio_sms",
        "delivered": True,
    }


def _fallback_delivery(channel, target, code, reason):
    logger.warning(
        "Verification delivery fallback for %s to %s: %s. Code=%s",
        channel,
        target,
        reason,
        code,
    )
    if not Config.AUTH_EXPOSE_VERIFICATION_CODE:
        raise RuntimeError(reason)

    return {
        "channel": channel,
        "target": target,
        "masked_target": mask_verification_target(channel, target),
        "delivery_method": "debug_fallback",
        "delivered": True,
        "preview_code": code,
        "warning": reason,
    }
