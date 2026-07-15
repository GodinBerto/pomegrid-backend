import os
from pathlib import Path


def _load_env_file():
    seen = set()
    candidates = []

    config_dir = Path(__file__).resolve().parent
    cwd_dir = Path.cwd().resolve()
    for base_dir in [config_dir, cwd_dir, *config_dir.parents, *cwd_dir.parents]:
        for file_name in (".env", ".env.local", ".env.development", ".env.production"):
            path = base_dir / file_name
            if path not in seen:
                seen.add(path)
                candidates.append(path)

    for env_file in candidates:
        if not env_file.exists() or not env_file.is_file():
            continue

        for raw_line in env_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


_load_env_file()


def _env_bool(name, default=False):
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return str(raw_value).strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name, default):
    raw_value = os.getenv(name)
    if raw_value is None:
        return float(default)
    try:
        return float(str(raw_value).strip())
    except (TypeError, ValueError):
        return float(default)


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY")
    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY")
    ADMIN_SETUP_KEY = os.environ.get("ADMIN_SETUP_KEY")
    BASE_URL = os.environ.get("BASE_URL")
    CLOUDINARY_API_KEY = os.environ.get("CLOUDINARY_API_KEY")
    CLOUDINARY_API_SECRET = os.environ.get("CLOUDINARY_API_SECRET")
    CLOUDINARY_API_NAME = os.environ.get("CLOUDINARY_API_NAME")
    REDIS_ENABLED = _env_bool("REDIS_ENABLED", True)
    REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
    REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
    REDIS_DB = int(os.environ.get("REDIS_DB", "0"))
    REDIS_SOCKET_CONNECT_TIMEOUT = _env_float("REDIS_SOCKET_CONNECT_TIMEOUT", 0.2)
    REDIS_SOCKET_TIMEOUT = _env_float("REDIS_SOCKET_TIMEOUT", 0.2)
    REDIS_UNAVAILABLE_RETRY_SECONDS = _env_float("REDIS_UNAVAILABLE_RETRY_SECONDS", 30.0)
    PAYSTACK_SECRET_KEY = os.environ.get("PAYSTACK_SECRET_KEY")
    PAYSTACK_PUBLIC_KEY = os.environ.get("PAYSTACK_PUBLIC_KEY")
    PAYSTACK_BASE_URL = os.environ.get("PAYSTACK_BASE_URL")
    PAYSTACK_CALLBACK_URL = os.environ.get("PAYSTACK_CALLBACK_URL")
    VERIFICATION_CODE_EXPIRY_MINUTES = int(os.environ.get("VERIFICATION_CODE_EXPIRY_MINUTES", "10"))
    VERIFICATION_EMAIL_SUBJECT = os.environ.get("VERIFICATION_EMAIL_SUBJECT")
    SMTP_HOST = os.environ.get("SMTP_HOST")
    SMTP_PORT = int(os.environ.get("SMTP_PORT"))
    SMTP_USERNAME = os.environ.get("SMTP_USERNAME")
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD")
    SMTP_USE_TLS = _env_bool("SMTP_USE_TLS")
    SMTP_USE_SSL = _env_bool("SMTP_USE_SSL")
    SMTP_FROM_EMAIL = os.environ.get("SMTP_FROM_EMAIL")
    SMTP_FROM_NAME = os.environ.get("SMTP_FROM_NAME")
    SMS_WEBHOOK_URL = os.environ.get("SMS_WEBHOOK_URL")
    SMS_WEBHOOK_TOKEN = os.environ.get("SMS_WEBHOOK_TOKEN")
    SMS_SENDER_ID = os.environ.get("SMS_SENDER_ID")
    AUTH_EXPOSE_VERIFICATION_CODE = _env_bool(
        "AUTH_EXPOSE_VERIFICATION_CODE",
        _env_bool("FLASK_DEBUG", True),
    )
