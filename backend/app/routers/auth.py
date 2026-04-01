"""Authentication router — registration, login, profile."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.db_models import User
from app.models.schemas import (
    AuthResponse, LoginRequest, RegisterRequest, UserProfile,
    SubscriptionRequest, SubscriptionResponse,
)
from app.config import settings
from app.services.auth import (
    create_access_token, get_current_user, hash_password, verify_password,
)
from app.services.payments import (
    create_customer, create_checkout_session, SUBSCRIPTION_PRICES,
    create_connected_account, create_account_onboarding_link, get_account_status,
)
from app.logging_config import log

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
limiter = Limiter(key_func=get_remote_address)


@router.post("/register", response_model=AuthResponse, status_code=201)
@limiter.limit("5/minute")
async def register(request: Request, req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """Create a new user account."""
    # Check existing
    existing = await db.execute(
        select(User).where((User.email == req.email) | (User.username == req.username))
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email or username already registered")

    # Create Stripe customer
    stripe_id = await create_customer(req.email, req.username)

    tier = "admin" if req.email in settings.ADMIN_EMAILS else "free"
    user = User(
        email=req.email,
        username=req.username,
        hashed_password=hash_password(req.password),
        stripe_customer_id=stripe_id,
        tier=tier,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_access_token(user.id)
    log.info(f"User registered: {user.username} ({user.email})")

    return AuthResponse(
        access_token=token,
        user=UserProfile(
            id=user.id,
            email=user.email,
            username=user.username,
            tier=user.tier,
            generation_count_this_month=0,
        ),
    )


@router.post("/login", response_model=AuthResponse)
@limiter.limit("10/minute")
async def login(request: Request, req: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Login and get access token."""
    result = await db.execute(select(User).where(User.email == req.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(req.password, user.hashed_password):
        log.warning(f"Failed login attempt for: {req.email}")
        raise HTTPException(status_code=401, detail="Invalid email or password")

    # Auto-promote admin if not already
    if user.email in settings.ADMIN_EMAILS and user.tier != "admin":
        user.tier = "admin"
        await db.commit()

    token = create_access_token(user.id)
    log.info(f"User logged in: {user.username}")

    return AuthResponse(
        access_token=token,
        user=UserProfile(
            id=user.id,
            email=user.email,
            username=user.username,
            tier=user.tier,
            generation_count_this_month=user.generation_count_this_month,
        ),
    )


@router.get("/me", response_model=UserProfile)
async def get_profile(user: User = Depends(get_current_user)):
    """Get current user profile."""
    return UserProfile(
        id=user.id,
        email=user.email,
        username=user.username,
        tier=user.tier,
        generation_count_this_month=user.generation_count_this_month,
    )


@router.post("/request-reset")
@limiter.limit("5/minute")
async def request_password_reset(
    request: Request,
    email: str,
    db: AsyncSession = Depends(get_db),
):
    """Request a password reset token. Returns the token directly (in production, email it)."""
    import secrets
    from datetime import timedelta
    from app.models.db_models import PasswordResetToken

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    # Always return success to avoid email enumeration
    if not user:
        return {"message": "If an account with that email exists, a reset link has been sent."}

    token = secrets.token_urlsafe(48)
    reset = PasswordResetToken(
        user_id=user.id,
        token=token,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db.add(reset)
    await db.commit()

    log.info(f"Password reset requested for: {user.email}")
    # In production: send email with reset link containing token
    # For now: return token directly so the frontend can use it
    return {"message": "If an account with that email exists, a reset link has been sent.", "reset_token": token}


@router.post("/reset-password")
async def reset_password(
    token: str,
    new_password: str,
    db: AsyncSession = Depends(get_db),
):
    """Reset password using a valid reset token."""
    from app.models.db_models import PasswordResetToken

    if len(new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    result = await db.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.token == token,
            PasswordResetToken.used == False,
        )
    )
    reset = result.scalar_one_or_none()
    if not reset:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    if reset.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Reset token has expired")

    # Find user and update password
    user_result = await db.execute(select(User).where(User.id == reset.user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=400, detail="Invalid reset token")

    user.hashed_password = hash_password(new_password)
    reset.used = True
    await db.commit()

    log.info(f"Password reset completed for: {user.email}")
    return {"message": "Password has been reset successfully."}


@router.post("/subscribe", response_model=SubscriptionResponse)
async def subscribe(
    req: SubscriptionRequest,
    user: User = Depends(get_current_user),
):
    """Start a subscription checkout via Stripe."""
    price_id = SUBSCRIPTION_PRICES.get(req.plan)
    if not price_id:
        raise HTTPException(status_code=400, detail=f"Invalid plan: {req.plan}")

    if not user.stripe_customer_id:
        raise HTTPException(status_code=400, detail="No payment profile. Contact support.")

    checkout_url = await create_checkout_session(
        customer_id=user.stripe_customer_id,
        price_id=price_id,
        success_url=req.success_url,
        cancel_url=req.cancel_url,
    )
    return SubscriptionResponse(checkout_url=checkout_url)


@router.post("/seller/onboard")
async def seller_onboard(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Start Stripe Connect onboarding for a seller."""
    if user.tier not in ("maker", "pro", "admin"):
        raise HTTPException(status_code=403, detail="Seller features require Maker or Pro subscription.")

    # Create connected account if not exists
    if not user.stripe_connect_account_id:
        account_id = await create_connected_account(user.email)
        user.stripe_connect_account_id = account_id
        await db.commit()
    else:
        account_id = user.stripe_connect_account_id

    # Create onboarding link using configured frontend URL
    base_url = settings.FRONTEND_URL or "http://localhost:5173"
    onboarding_url = await create_account_onboarding_link(
        account_id=account_id,
        refresh_url=f"{base_url}/seller/onboard",
        return_url=f"{base_url}/seller/dashboard",
    )

    return {"onboarding_url": onboarding_url}


@router.get("/seller/status")
async def seller_status(user: User = Depends(get_current_user)):
    """Check seller payout account status."""
    if not user.stripe_connect_account_id:
        return {
            "has_account": False,
            "payouts_enabled": False,
            "charges_enabled": False,
            "details_submitted": False,
        }

    status = await get_account_status(user.stripe_connect_account_id)
    return {
        "has_account": True,
        **status,
    }
