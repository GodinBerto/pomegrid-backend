import os


def _env_bool(name, default=False):
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return str(raw_value).strip().lower() in {"1", "true", "yes", "on"}


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "your_secret_key")
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "your_jwt_secret_key")
    ADMIN_SETUP_KEY = os.getenv("ADMIN_SETUP_KEY", "change_this_admin_setup_key")
    BASE_URL = os.getenv("BASE_URL", "/api/v1")
    CLOUDINARY_API_KEY = os.getenv("CLOUDINARY_API_KEY", "228894397371284")
    CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET", "pxSV1WRyZsTOCbHoMtA5ZoOMh1s")
    CLOUDINARY_API_NAME = os.getenv("CLOUDINARY_API_NAME", " dquhjbcvq")
    REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
    PAYSTACK_PUBLIC_KEY = os.getenv("PAYSTACK_PUBLIC_KEY", "pk_test_438f3137c4492b7d7705a17d2b5a303062f066b9")
    PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY", "sk_test_f187d9cea58b912cfc4ac9b71886a82476c3d5e2")
    PAYSTACK_BASE_URL = os.getenv("PAYSTACK_BASE_URL", "https://api.paystack.co")
    PAYSTACK_CALLBACK_URL = os.getenv("PAYSTACK_CALLBACK_URL", "")
    VERIFICATION_CODE_EXPIRY_MINUTES = int(os.getenv("VERIFICATION_CODE_EXPIRY_MINUTES", "10"))
    VERIFICATION_EMAIL_SUBJECT = os.getenv("VERIFICATION_EMAIL_SUBJECT", "Your Pomegrid verification code")
    SMTP_HOST = os.getenv("SMTP_HOST", "")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USERNAME = os.getenv("SMTP_USERNAME", "godfredquarm123@gmail.com")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "contqwqfohdotguc")
    SMTP_USE_TLS = _env_bool("SMTP_USE_TLS", True)
    SMTP_USE_SSL = _env_bool("SMTP_USE_SSL", False)
    SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL", "godfredquarm123@gmail.com")
    SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "Pomegrid")
    SMS_WEBHOOK_URL = os.getenv("SMS_WEBHOOK_URL", "")
    SMS_WEBHOOK_TOKEN = os.getenv("SMS_WEBHOOK_TOKEN", "")
    SMS_SENDER_ID = os.getenv("SMS_SENDER_ID", "Pomegrid")
    AUTH_EXPOSE_VERIFICATION_CODE = _env_bool(
        "AUTH_EXPOSE_VERIFICATION_CODE",
        _env_bool("FLASK_DEBUG", True),
    )
