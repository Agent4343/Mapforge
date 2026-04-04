"""Admin dashboard router — platform stats and settings for admin users."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.db_models import GeneratedFile, MarketplaceListing, Purchase, User
from app.services.app_settings import (
    get_setting,
    set_setting,
    delete_setting,
    get_maptiler_only_mode,
)
from app.services.auth import get_current_user
from app.logging_config import log

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


def _require_admin(user: User):
    """Raise 403 if the user is not an admin."""
    if user.tier != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")


@router.get("/stats")
async def admin_stats(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return admin dashboard statistics."""
    _require_admin(user)

    # Total counts
    total_users = (await db.execute(select(func.count()).select_from(User))).scalar() or 0
    total_files = (await db.execute(select(func.count()).select_from(GeneratedFile))).scalar() or 0
    total_listings = (await db.execute(select(func.count()).select_from(MarketplaceListing))).scalar() or 0
    total_sales = (await db.execute(select(func.count()).select_from(Purchase))).scalar() or 0

    # Revenue
    revenue_cents = (
        await db.execute(select(func.coalesce(func.sum(Purchase.price_cents), 0)))
    ).scalar() or 0

    # Users by tier
    tier_rows = (
        await db.execute(
            select(User.tier, func.count()).group_by(User.tier)
        )
    ).all()
    users_by_tier = {"free": 0, "maker": 0, "pro": 0, "admin": 0}
    for tier, count in tier_rows:
        users_by_tier[tier] = count

    # Recent files (last 10) with owner username
    recent_query = (
        select(
            GeneratedFile.location_name,
            GeneratedFile.product_type,
            GeneratedFile.created_at,
            User.username,
        )
        .join(User, GeneratedFile.owner_id == User.id)
        .order_by(GeneratedFile.created_at.desc())
        .limit(10)
    )
    recent_rows = (await db.execute(recent_query)).all()
    recent_files = [
        {
            "location_name": row.location_name,
            "product_type": row.product_type,
            "created_at": row.created_at.isoformat(),
            "owner_username": row.username,
        }
        for row in recent_rows
    ]

    return {
        "total_users": total_users,
        "total_files": total_files,
        "total_listings": total_listings,
        "total_sales": total_sales,
        "revenue_cents": revenue_cents,
        "recent_files": recent_files,
        "users_by_tier": users_by_tier,
    }


# --- Etsy API Settings ---

ETSY_SETTING_KEYS = ["ETSY_API_KEY", "ETSY_API_SECRET", "ETSY_REDIRECT_URI"]


class EtsySettingsRequest(BaseModel):
    api_key: str = ""
    api_secret: str = ""
    redirect_uri: str = ""


@router.get("/etsy-settings")
async def get_etsy_settings(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get current Etsy API settings (admin only). Secrets are masked."""
    _require_admin(user)

    api_key = await get_setting(db, "ETSY_API_KEY") or ""
    api_secret = await get_setting(db, "ETSY_API_SECRET") or ""
    redirect_uri = await get_setting(db, "ETSY_REDIRECT_URI") or ""

    # Show the constructed x-api-key format for debugging (masked)
    key_trimmed = api_key.strip()
    secret_trimmed = api_secret.strip()
    header_preview = f"{key_trimmed[:8]}...({len(key_trimmed)}ch):{secret_trimmed[:4]}...({len(secret_trimmed)}ch)" if key_trimmed and secret_trimmed else "NOT CONFIGURED"

    return {
        "api_key": api_key[:8] + "..." if len(api_key) > 8 else api_key,
        "api_secret": "••••••••" if api_secret else "",
        "redirect_uri": redirect_uri,
        "configured": bool(api_key and api_secret),
        "header_format": header_preview,
    }


@router.post("/etsy-settings")
async def save_etsy_settings(
    req: EtsySettingsRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Save Etsy API credentials to the database (admin only)."""
    _require_admin(user)

    if req.api_key:
        await set_setting(db, "ETSY_API_KEY", req.api_key.strip())
    if req.api_secret:
        await set_setting(db, "ETSY_API_SECRET", req.api_secret.strip())
    if req.redirect_uri:
        await set_setting(db, "ETSY_REDIRECT_URI", req.redirect_uri.strip())

    return {"status": "saved"}


@router.delete("/etsy-settings")
async def clear_etsy_settings(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Clear Etsy API credentials from the database (admin only)."""
    _require_admin(user)

    for key in ETSY_SETTING_KEYS:
        await delete_setting(db, key)

    return {"status": "cleared"}


# --- MapTiler Settings ---

MAPTILER_SETTING_KEYS = [
    "MAPTILER_KEY",
    "VITE_MAPTILER_KEY",
    "MAPTILER_STATIC_STYLE",
    "MAPFORGE_MAPTILER_ONLY_MODE",
    "MAPTILER_ONLY_MODE",
]


class MapTilerSettingsRequest(BaseModel):
    api_key: str = ""
    static_style: str = ""
    maptiler_only_mode: bool = False


@router.get("/maptiler-settings")
async def get_maptiler_settings(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get current MapTiler settings (admin only). API key is masked."""
    _require_admin(user)

    api_key = (
        (await get_setting(db, "MAPTILER_KEY"))
        or (await get_setting(db, "VITE_MAPTILER_KEY"))
        or ""
    ).strip()
    static_style = ((await get_setting(db, "MAPTILER_STATIC_STYLE")) or "").strip()
    maptiler_only_mode = await get_maptiler_only_mode(db)

    return {
        "api_key": api_key[:8] + "..." if len(api_key) > 8 else api_key,
        "static_style": static_style or "basic-v2",
        "maptiler_only_mode": bool(maptiler_only_mode),
        "configured": bool(api_key),
    }


@router.post("/maptiler-settings")
async def save_maptiler_settings(
    req: MapTilerSettingsRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Save MapTiler settings to the database (admin only)."""
    _require_admin(user)

    api_key = (req.api_key or "").strip()
    static_style = (req.static_style or "").strip()

    if api_key:
        # Write both keys so frontend/backend code paths remain compatible.
        await set_setting(db, "MAPTILER_KEY", api_key)
        await set_setting(db, "VITE_MAPTILER_KEY", api_key)
    if static_style:
        await set_setting(db, "MAPTILER_STATIC_STYLE", static_style)

    mode_val = "1" if req.maptiler_only_mode else "0"
    await set_setting(db, "MAPFORGE_MAPTILER_ONLY_MODE", mode_val)
    await set_setting(db, "MAPTILER_ONLY_MODE", mode_val)

    return {"status": "saved"}


@router.delete("/maptiler-settings")
async def clear_maptiler_settings(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Clear MapTiler settings from the database (admin only)."""
    _require_admin(user)

    for key in MAPTILER_SETTING_KEYS:
        await delete_setting(db, key)

    return {"status": "cleared"}


@router.get("/etsy-debug")
async def etsy_debug(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Debug Etsy API connection (admin only). Tests the x-api-key header."""
    _require_admin(user)

    from app.services.app_settings import get_etsy_credentials
    creds = await get_etsy_credentials(db)

    key = creds.get("api_key", "")
    secret = creds.get("api_secret", "")

    # Check for common issues
    issues = []
    if not key:
        issues.append("API Key (Keystring) is empty")
    if not secret:
        issues.append("Shared Secret is empty")
    if key and " " in key:
        issues.append("API Key contains spaces")
    if secret and " " in secret:
        issues.append("Shared Secret contains spaces")
    if key and "\n" in key:
        issues.append("API Key contains newlines")
    if secret and "\n" in secret:
        issues.append("Shared Secret contains newlines")

    # Try a simple API call to test
    test_result = None
    if key and secret:
        import httpx
        header_val = f"{key}:{secret}"
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    "https://api.etsy.com/v3/application/openapi-ping",
                    headers={"x-api-key": header_val},
                    timeout=10.0,
                )
                test_result = {
                    "status_code": resp.status_code,
                    "response": resp.text[:300],
                }
        except Exception as e:
            test_result = {"error": str(e)}

    return {
        "key_length": len(key),
        "secret_length": len(secret),
        "key_preview": f"{key[:8]}...{key[-4:]}" if len(key) > 12 else key,
        "secret_preview": f"{secret[:4]}...{secret[-4:]}" if len(secret) > 8 else "TOO_SHORT",
        "header_format": f"{key[:6]}..:{secret[:4]}..",
        "issues": issues,
        "ping_test": test_result,
        "redirect_uri": creds.get("redirect_uri", ""),
    }


# --- Cache Management ---

@router.post("/clear-cache")
async def clear_geometry_cache(
    user: User = Depends(get_current_user),
):
    """Clear all geometry and overpass caches (admin only).

    Use this after code changes to province rendering to ensure fresh data.
    """
    _require_admin(user)

    cleared = []

    # Clear in-memory overpass cache (streets/water)
    try:
        from app.routers.generate import _overpass_cache
        count = len(_overpass_cache)
        _overpass_cache.clear()
        cleared.append(f"overpass_memory: {count} entries")
    except Exception as e:
        cleared.append(f"overpass_memory: error ({e})")

    # Clear Redis geometry cache (all geom:* keys)
    try:
        from app.services.cache import _get_redis
        client = await _get_redis()
        if client:
            keys = []
            async for key in client.scan_iter(match="geom:*", count=100):
                keys.append(key)
            if keys:
                await client.delete(*keys)
            cleared.append(f"redis_geometry: {len(keys)} keys")
        else:
            cleared.append("redis_geometry: no redis connection")
    except Exception as e:
        cleared.append(f"redis_geometry: error ({e})")

    log.info(f"Admin cache clear: {cleared}")
    return {"status": "cleared", "details": cleared}
