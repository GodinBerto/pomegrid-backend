import os


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
    PAYSTACK_PUBLIC_KEY = os.getenv("PAYSTACK_PUBLIC_KEY", "")
    PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY", "")
    PAYSTACK_BASE_URL = os.getenv("PAYSTACK_BASE_URL", "https://api.paystack.co")
    PAYSTACK_CALLBACK_URL = os.getenv("PAYSTACK_CALLBACK_URL", "")
