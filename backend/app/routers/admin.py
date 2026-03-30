"""Admin dashboard router — platform stats and settings for admin users."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.db_models import GeneratedFile, MarketplaceListing, Purchase, User
from app.services.app_settings import get_setting, set_setting, delete_setting
from app.services.auth import get_current_user

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

    # Try a simple API call to test connectivity (credentials used only in-flight)
    test_result = None
    if key and secret:
        import httpx
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    "https://api.etsy.com/v3/application/openapi-ping",
                    headers={"x-api-key": f"{key}:{secret}"},
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
        "key_configured": bool(key),
        "secret_configured": bool(secret),
        "issues": issues,
        "ping_test": test_result,
        "redirect_uri": creds.get("redirect_uri", ""),
    }
