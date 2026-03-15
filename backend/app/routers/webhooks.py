"""Stripe webhook handler for subscription and payment events."""

from fastapi import APIRouter, Request, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.logging_config import log
from app.models.db_models import User
from app.services.payments import verify_webhook_signature

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])

PLAN_TIER_MAP = {
    "price_maker_monthly": "maker",
    "price_maker_annual": "maker",
    "price_pro_monthly": "pro",
    "price_pro_annual": "pro",
}


@router.post("/stripe")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events."""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = verify_webhook_signature(payload, sig_header)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Webhook verification failed: {e}")

    event_type = event.get("type", "")
    data = event.get("data", {}).get("object", {})

    log.info(f"Stripe webhook: {event_type}")

    async with async_session() as db:
        if event_type == "checkout.session.completed":
            await _handle_checkout_completed(db, data)
        elif event_type == "customer.subscription.updated":
            await _handle_subscription_updated(db, data)
        elif event_type == "customer.subscription.deleted":
            await _handle_subscription_deleted(db, data)
        elif event_type == "invoice.payment_failed":
            await _handle_payment_failed(db, data)

    return {"status": "ok"}


async def _handle_checkout_completed(db: AsyncSession, data: dict):
    """Handle successful checkout — activate subscription."""
    customer_id = data.get("customer")
    subscription_id = data.get("subscription")

    if not customer_id or not subscription_id:
        return

    result = await db.execute(
        select(User).where(User.stripe_customer_id == customer_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        log.warning(f"No user found for Stripe customer: {customer_id}")
        return

    # Determine tier from subscription items
    items = data.get("display_items", []) or []
    tier = "maker"  # default
    for item in items:
        price_id = item.get("price", {}).get("id", "")
        if price_id in PLAN_TIER_MAP:
            tier = PLAN_TIER_MAP[price_id]
            break

    user.tier = tier
    user.stripe_subscription_id = subscription_id
    await db.commit()
    log.info(f"User {user.username} upgraded to {tier}")


async def _handle_subscription_updated(db: AsyncSession, data: dict):
    """Handle subscription plan change."""
    customer_id = data.get("customer")
    status = data.get("status")

    result = await db.execute(
        select(User).where(User.stripe_customer_id == customer_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        return

    if status == "active":
        items = data.get("items", {}).get("data", [])
        for item in items:
            price_id = item.get("price", {}).get("id", "")
            if price_id in PLAN_TIER_MAP:
                user.tier = PLAN_TIER_MAP[price_id]
                break
    elif status in ("past_due", "unpaid"):
        log.warning(f"Subscription past due for user {user.username}")

    await db.commit()


async def _handle_subscription_deleted(db: AsyncSession, data: dict):
    """Handle subscription cancellation — downgrade to free."""
    customer_id = data.get("customer")

    result = await db.execute(
        select(User).where(User.stripe_customer_id == customer_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        return

    user.tier = "free"
    user.stripe_subscription_id = None
    await db.commit()
    log.info(f"User {user.username} downgraded to free (subscription cancelled)")


async def _handle_payment_failed(db: AsyncSession, data: dict):
    """Log payment failure."""
    customer_id = data.get("customer")
    log.warning(f"Payment failed for customer: {customer_id}")
