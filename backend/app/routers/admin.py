"""Admin dashboard router — platform stats for admin users."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.db_models import GeneratedFile, MarketplaceListing, Purchase, User
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
