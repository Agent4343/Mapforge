"""Application configuration from environment variables."""

import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:////tmp/mapforge.db")

    # Auth
    SECRET_KEY: str = os.getenv("SECRET_KEY", "mapforge-dev-secret-change-in-production")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))
    ALGORITHM: str = "HS256"

    # Stripe
    STRIPE_SECRET_KEY: str = os.getenv("STRIPE_SECRET_KEY", "")
    STRIPE_WEBHOOK_SECRET: str = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    PLATFORM_FEE_PERCENT_MAKER: float = 25.0
    PLATFORM_FEE_PERCENT_PRO: float = 15.0

    # File storage
    STORAGE_BACKEND: str = os.getenv("STORAGE_BACKEND", "local")  # "local" or "s3"
    STORAGE_LOCAL_PATH: str = os.getenv("STORAGE_LOCAL_PATH", "/tmp/mapforge_storage")
    S3_BUCKET: str = os.getenv("S3_BUCKET", "")
    S3_REGION: str = os.getenv("S3_REGION", "us-east-1")
    S3_ENDPOINT: str = os.getenv("S3_ENDPOINT", "")
    S3_ACCESS_KEY: str = os.getenv("S3_ACCESS_KEY", "")
    S3_SECRET_KEY: str = os.getenv("S3_SECRET_KEY", "")

    # Rate limiting
    RATE_LIMIT_SEARCH: str = "10/minute"
    RATE_LIMIT_GENERATE: str = "5/minute"
    RATE_LIMIT_BATCH: str = "2/minute"

    # Nominatim
    NOMINATIM_RATE_LIMIT: float = 1.0  # max 1 request per second

    # CORS
    FRONTEND_URL: str = os.getenv("FRONTEND_URL", "")

    # Subscription limits
    FREE_PROVINCE_LIMIT: int = 3
    FREE_LIBRARY_LIMIT: int = 5
    MAKER_MONTHLY_LIMIT: int = 20
    MAKER_LIBRARY_LIMIT: int = 100
    PRO_BATCH_LIMIT: int = 50


settings = Settings()
