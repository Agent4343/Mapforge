"""Stripe webhook handler for subscription, payment, and payout events."""

from fastapi import APIRouter, Request, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.logging_config import log
from app.models.db_models import User, Purchase, MarketplaceListing
from app.services.payments import verify_webhook_signature, create_transfer

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
        elif event_type == "invoice.payment_succeeded":
            await _handle_payment_succeeded(db, data)
        elif event_type == "payment_intent.succeeded":
            await _handle_marketplace_payment(db, data)
        elif event_type == "account.updated":
            await _handle_account_updated(db, data)

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


async def _handle_payment_succeeded(db: AsyncSession, data: dict):
    """Handle successful invoice payment — reset monthly generation count."""
    customer_id = data.get("customer")

    result = await db.execute(
        select(User).where(User.stripe_customer_id == customer_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        return

    # Reset monthly generation count on successful subscription renewal
    user.generation_count_this_month = 0
    await db.commit()
    log.info(f"Monthly count reset for {user.username} on successful payment")


async def _handle_marketplace_payment(db: AsyncSession, data: dict):
    """Handle successful marketplace purchase — transfer funds to seller."""
    transfer_group = data.get("transfer_group")
    metadata = data.get("metadata", {})
    purchase_id = metadata.get("purchase_id")

    if not purchase_id:
        return

    result = await db.execute(
        select(Purchase).where(Purchase.id == purchase_id)
    )
    purchase = result.scalar_one_or_none()
    if not purchase or purchase.status != "pending":
        return

    # Get the listing and seller
    listing_result = await db.execute(
        select(MarketplaceListing).where(MarketplaceListing.id == purchase.listing_id)
    )
    listing = listing_result.scalar_one_or_none()
    if not listing:
        return

    seller_result = await db.execute(
        select(User).where(User.id == listing.seller_id)
    )
    seller = seller_result.scalar_one_or_none()
    if not seller or not seller.stripe_connect_account_id:
        log.warning(f"Seller {listing.seller_id} has no connected account for payout")
        purchase.status = "completed"
        await db.commit()
        return

    # Transfer seller's share to their connected account
    if seller.stripe_payouts_enabled and purchase.seller_payout_cents > 0:
        try:
            transfer_id = await create_transfer(
                amount_cents=purchase.seller_payout_cents,
                destination_account=seller.stripe_connect_account_id,
                transfer_group=transfer_group,
            )
            if transfer_id:
                log.info(f"Transfer {transfer_id} created for seller {seller.username}: ${purchase.seller_payout_cents/100:.2f}")
        except Exception as e:
            log.error(f"Failed to transfer to seller {seller.username}: {e}")

    purchase.status = "completed"
    listing.sale_count += 1  # increment for async payments that were initially "pending"
    await db.commit()


async def _handle_account_updated(db: AsyncSession, data: dict):
    """Handle Stripe Connect account updates — track payout readiness."""
    account_id = data.get("id")
    payouts_enabled = data.get("payouts_enabled", False)
    charges_enabled = data.get("charges_enabled", False)

    result = await db.execute(
        select(User).where(User.stripe_connect_account_id == account_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        return

    user.stripe_payouts_enabled = payouts_enabled
    await db.commit()
    log.info(f"Account {account_id} updated: payouts={payouts_enabled}, charges={charges_enabled}")
