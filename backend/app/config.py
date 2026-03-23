"""Application configuration from environment variables."""

import os
from dotenv import load_dotenv

load_dotenv()


def _fixup_db_url(url: str) -> str:
    """Convert any Postgres URL variant to postgresql+asyncpg:// for SQLAlchemy async."""
    # Railway may prefix with "type: " — find the actual URL
    for scheme in ("postgresql://", "postgres://"):
        idx = url.find(scheme)
        if idx != -1:
            return "postgresql+asyncpg://" + url[idx + len(scheme):]
    return url


class Settings:
    # Database
    DATABASE_URL: str = _fixup_db_url(os.getenv("DATABASE_URL", "sqlite+aiosqlite:////tmp/mapforge.db"))

    # Auth — SECRET_KEY must be set in production via environment variable
    SECRET_KEY: str = os.getenv("SECRET_KEY", "")
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

    # Redis (optional caching layer)
    REDIS_URL: str = os.getenv("REDIS_URL", "")
    CACHE_TTL_SEARCH: int = 3600  # 1 hour
    CACHE_TTL_GEOMETRY: int = 86400  # 24 hours

    # Subscription limits
    FREE_PROVINCE_LIMIT: int = 3
    FREE_LIBRARY_LIMIT: int = 5
    MAKER_MONTHLY_LIMIT: int = 20
    MAKER_LIBRARY_LIMIT: int = 100
    PRO_BATCH_LIMIT: int = 50

    # AI Description Generation (Claude API)
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")

    # Etsy API (OAuth 2.0 — register at https://www.etsy.com/developers)
    ETSY_API_KEY: str = os.getenv("ETSY_API_KEY", "")
    ETSY_API_SECRET: str = os.getenv("ETSY_API_SECRET", "")
    ETSY_REDIRECT_URI: str = os.getenv("ETSY_REDIRECT_URI", "http://localhost:8000/api/v1/etsy/callback")

    # Admin — set via ADMIN_EMAILS env var (comma-separated)
    ADMIN_EMAILS: list[str] = [e.strip() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()]

    # Seller payouts
    STRIPE_PAYOUT_DELAY_DAYS: int = 7  # Days before payout to sellers


settings = Settings()
