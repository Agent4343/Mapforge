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


def _parse_env_bool(raw: str | None) -> bool:
    """Parse env boolean values, tolerating common quoted forms."""
    normalized = str(raw or "").strip()
    if normalized.startswith(("'", '"')) and normalized.endswith(("'", '"')) and len(normalized) >= 2:
        normalized = normalized[1:-1].strip()
    normalized = normalized.lower()
    return normalized in {"1", "true", "yes", "on", "enabled"}


def _first_non_empty_env(*keys: str) -> str:
    """Return first non-empty env var value among provided keys."""
    for key in keys:
        value = os.getenv(key)
        if value is not None and str(value).strip() != "":
            return value
    return ""


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

    # Etsy shop URL (shown to customers as the purchase link)
    ETSY_SHOP_URL: str = os.getenv("ETSY_SHOP_URL", "")

    # MapTiler key for browser-side map preview.
    # Supports both MAPTILER_KEY and VITE_MAPTILER_KEY for deployment flexibility.
    MAPTILER_KEY: str = os.getenv("MAPTILER_KEY", os.getenv("VITE_MAPTILER_KEY", ""))
    MAPTILER_STATIC_STYLE: str = os.getenv("MAPTILER_STATIC_STYLE", "streets-v2")
    # When enabled, customer generation skips Overpass overlays and uses
    # MapTiler-only preview/export composition to avoid Overpass instability.
    # Backward-compatible with older MAPTILER_ONLY_MODE naming.
    MAPFORGE_MAPTILER_ONLY_MODE: bool = _parse_env_bool(
        _first_non_empty_env("MAPFORGE_MAPTILER_ONLY_MODE", "MAPTILER_ONLY_MODE")
    )

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
    ETSY_WEBHOOK_SECRET: str = os.getenv("ETSY_WEBHOOK_SECRET", "")

    # Admin — set via ADMIN_EMAILS env var (comma-separated)
    ADMIN_EMAILS: list[str] = [e.strip() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()]

    # Seller payouts
    STRIPE_PAYOUT_DELAY_DAYS: int = 7  # Days before payout to sellers


settings = Settings()
