import json
import logging
import smtplib
from email.message import EmailMessage
from secrets import randbelow
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
        target = str(phone or "").strip()
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
    webhook_url = str(Config.SMS_WEBHOOK_URL or "").strip()
    if not webhook_url:
        return _fallback_delivery("phone", target, code, "SMS delivery is not configured")

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
