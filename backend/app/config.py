"""Application configuration from environment variables."""

import os
import secrets
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


def _get_secret_key() -> str:
    """Get SECRET_KEY from environment. Generates a random one for development only."""
    key = os.getenv("SECRET_KEY", "")
    if key:
        return key
    # In production (Railway sets RAILWAY_ENVIRONMENT), SECRET_KEY is required
    if os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("PRODUCTION"):
        raise RuntimeError(
            "SECRET_KEY environment variable is required in production. "
            "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(64))\""
        )
    # Development fallback — generate a random key (tokens won't survive restarts)
    return secrets.token_urlsafe(64)


def _parse_admin_emails() -> list[str]:
    """Parse admin emails from ADMIN_EMAILS env var (comma-separated)."""
    raw = os.getenv("ADMIN_EMAILS", "")
    if raw:
        return [e.strip().lower() for e in raw.split(",") if e.strip()]
    return []


class Settings:
    # Database
    DATABASE_URL: str = _fixup_db_url(os.getenv("DATABASE_URL", "sqlite+aiosqlite:////tmp/mapforge.db"))

    # Auth
    SECRET_KEY: str = _get_secret_key()
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

    # Admin — loaded from env (comma-separated list of emails)
    ADMIN_EMAILS: list[str] = _parse_admin_emails()

    # Seller payouts
    STRIPE_PAYOUT_DELAY_DAYS: int = 7  # Days before payout to sellers

    @property
    def is_production(self) -> bool:
        return bool(os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("PRODUCTION"))

    @property
    def stripe_configured(self) -> bool:
        return bool(self.STRIPE_SECRET_KEY)

    def validate_production(self) -> list[str]:
        """Validate that required settings are configured for production.
        Returns list of warnings/errors."""
        issues = []
        if not self.STRIPE_SECRET_KEY:
            issues.append("STRIPE_SECRET_KEY not set — payments will be disabled")
        if not self.STRIPE_WEBHOOK_SECRET:
            issues.append("STRIPE_WEBHOOK_SECRET not set — webhooks will be disabled")
        if self.DATABASE_URL.startswith("sqlite"):
            issues.append("Using SQLite — not recommended for production (set DATABASE_URL to PostgreSQL)")
        if self.STORAGE_BACKEND == "s3" and not self.S3_BUCKET:
            issues.append("STORAGE_BACKEND=s3 but S3_BUCKET is empty")
        if not self.ADMIN_EMAILS:
            issues.append("ADMIN_EMAILS not set — no admin accounts will be created")
        if not self.FRONTEND_URL and not os.environ.get("RAILWAY_PUBLIC_DOMAIN"):
            issues.append("FRONTEND_URL not set — CORS may block frontend requests (ignored on Railway)")
        return issues


settings = Settings()
