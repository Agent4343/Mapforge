"""Read/write application settings from the database.

Settings stored in the app_settings table override environment variables.
This allows admin to configure Etsy API keys etc. via the UI.
"""

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db_models import AppSettings


async def get_setting(db: AsyncSession, key: str) -> Optional[str]:
    """Get a setting value from the database, or None if not set."""
    result = await db.execute(select(AppSettings).where(AppSettings.key == key))
    row = result.scalar_one_or_none()
    return row.value if row else None


async def set_setting(db: AsyncSession, key: str, value: str) -> None:
    """Set a setting value in the database (upsert)."""
    result = await db.execute(select(AppSettings).where(AppSettings.key == key))
    row = result.scalar_one_or_none()
    if row:
        row.value = value
    else:
        db.add(AppSettings(key=key, value=value))
    await db.commit()


async def delete_setting(db: AsyncSession, key: str) -> None:
    """Delete a setting from the database."""
    result = await db.execute(select(AppSettings).where(AppSettings.key == key))
    row = result.scalar_one_or_none()
    if row:
        await db.delete(row)
        await db.commit()


async def get_etsy_credentials(db: AsyncSession) -> dict:
    """Get Etsy API credentials, preferring DB values over env vars."""
    from app.config import settings

    api_key = (await get_setting(db, "ETSY_API_KEY") or settings.ETSY_API_KEY or "").strip()
    api_secret = (await get_setting(db, "ETSY_API_SECRET") or settings.ETSY_API_SECRET or "").strip()
    redirect_uri = (await get_setting(db, "ETSY_REDIRECT_URI") or settings.ETSY_REDIRECT_URI or "").strip()

    return {
        "api_key": api_key,
        "api_secret": api_secret,
        "redirect_uri": redirect_uri,
    }


async def get_maptiler_key(db: AsyncSession) -> str:
    """Get MapTiler key from DB settings, falling back to environment."""
    from app.config import settings

    return (
        (await get_setting(db, "MAPTILER_KEY"))
        or (await get_setting(db, "VITE_MAPTILER_KEY"))
        or settings.MAPTILER_KEY
        or ""
    ).strip()
