"""Stripe and Etsy webhook handlers for subscription, payment, and order events."""

import base64
import hashlib
import hmac
import time

from fastapi import APIRouter, Request, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session
from app.logging_config import log
from app.models.db_models import User, Purchase, MarketplaceListing, Order
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
        log.error(f"Stripe webhook verification failed: {type(e).__name__}: {e}")
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    event_type = event.get("type", "")
    data = event.get("data", {}).get("object", {})

    log.info(f"Stripe webhook: {event_type}")

    async with async_session() as db:
        if event_type == "checkout.session.completed":
            # Check if this is a map order (pay-per-design) or subscription
            metadata = data.get("metadata", {})
            if metadata.get("order_type") == "map_design":
                await _handle_order_checkout_completed(db, data, metadata)
            else:
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


async def _handle_order_checkout_completed(db: AsyncSession, data: dict, metadata: dict):
    """Handle pay-per-design checkout completion — generate the map files."""
    import json
    import asyncio
    from datetime import datetime, timezone

    order_id = metadata.get("order_id")
    if not order_id:
        log.warning("Order checkout completed but no order_id in metadata")
        return

    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        log.warning(f"Order {order_id} not found for checkout completion")
        return

    order.status = "paid"
    order.paid_at = datetime.now(timezone.utc)
    order.stripe_payment_intent_id = data.get("payment_intent")
    await db.commit()
    log.info(f"Order {order_id} marked as paid — starting generation")

    # Trigger async generation (fire-and-forget within the webhook)
    asyncio.create_task(_fulfill_order(order_id))


async def _fulfill_order(order_id: str):
    """Generate map files for a paid order."""
    import json
    from datetime import datetime, timezone
    from app.routers.generate import _do_generate
    from app.models.schemas import GenerateRequest

    async with async_session() as db:
        result = await db.execute(select(Order).where(Order.id == order_id))
        order = result.scalar_one_or_none()
        if not order or order.status not in ("paid",):
            return

        order.status = "generating"
        await db.commit()

    try:
        design = json.loads(order.design_config)

        # Build a proper GenerateRequest from the stored config
        req = GenerateRequest(**design)

        async with async_session() as db:
            gen_response = await _do_generate(req, user=None, db=db)

        async with async_session() as db:
            result = await db.execute(select(Order).where(Order.id == order_id))
            order = result.scalar_one()
            order.file_id = gen_response.file_id
            order.status = "completed"
            order.completed_at = datetime.now(timezone.utc)
            await db.commit()

        log.info(f"Order {order_id} fulfilled — file_id={gen_response.file_id}")
    except Exception as e:
        log.error(f"Order {order_id} generation failed: {e}")
        async with async_session() as db:
            result = await db.execute(select(Order).where(Order.id == order_id))
            order = result.scalar_one()
            order.status = "failed"
            await db.commit()


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


# =============================================================================
# Etsy Webhooks
# =============================================================================

def _verify_etsy_signature(payload: bytes, headers: dict) -> bool:
    """Verify Etsy webhook signature using HMAC-SHA256.

    Per Etsy docs:
      signed_content = webhook-id + "." + webhook-timestamp + "." + raw_body
      secret_bytes = base64_decode(secret.split("_")[1])
      expected_sig = base64_encode(HMAC_SHA256(secret_bytes, signed_content))
    """
    secret = settings.ETSY_WEBHOOK_SECRET
    if not secret:
        log.warning("ETSY_WEBHOOK_SECRET not set — skipping signature verification")
        return True

    webhook_id = headers.get("webhook-id", "")
    webhook_timestamp = headers.get("webhook-timestamp", "")
    webhook_signature = headers.get("webhook-signature", "")

    if not webhook_id or not webhook_timestamp or not webhook_signature:
        return False

    # Reject stale timestamps (>5 min drift)
    try:
        ts = int(webhook_timestamp)
        if abs(time.time() - ts) > 300:
            log.warning("Etsy webhook rejected: stale timestamp (%d vs %d)", ts, int(time.time()))
            return False
    except ValueError:
        return False

    # Derive secret key: remove "whsec_" prefix, base64-decode
    secret_part = secret.split("_", 1)[-1] if "_" in secret else secret
    try:
        secret_bytes = base64.b64decode(secret_part)
    except Exception:
        log.error("Failed to decode ETSY_WEBHOOK_SECRET")
        return False

    # Compute expected signature
    signed_content = f"{webhook_id}.{webhook_timestamp}.{payload.decode('utf-8')}"
    expected = base64.b64encode(
        hmac.new(secret_bytes, signed_content.encode("utf-8"), hashlib.sha256).digest()
    ).decode("ascii")

    # Compare against all signatures in the header (space-separated)
    for sig in webhook_signature.split(" "):
        # Signatures may have a version prefix like "v1,"
        sig_value = sig.split(",", 1)[-1] if "," in sig else sig
        if hmac.compare_digest(expected, sig_value):
            return True

    return False


@router.post("/etsy")
async def etsy_webhook(request: Request):
    """Handle Etsy webhook events (order.paid, order.shipped, etc.).

    Etsy sends real-time notifications when orders are placed, shipped,
    or cancelled. We sync these events back to the seller's dashboard.
    """
    payload = await request.body()
    headers = dict(request.headers)

    if not _verify_etsy_signature(payload, headers):
        raise HTTPException(status_code=400, detail="Invalid Etsy webhook signature")

    import json
    try:
        event = json.loads(payload)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event_type = event.get("event_type", "")
    data = event.get("data", event)
    shop_id = str(data.get("shop_id", ""))

    log.info(f"Etsy webhook: {event_type} for shop {shop_id}")

    async with async_session() as db:
        if event_type == "order.paid":
            await _handle_etsy_order_paid(db, data, shop_id)
        elif event_type == "order.canceled":
            await _handle_etsy_order_canceled(db, data, shop_id)
        elif event_type == "order.shipped":
            log.info(f"Etsy order shipped for shop {shop_id}")
        elif event_type == "order.delivered":
            log.info(f"Etsy order delivered for shop {shop_id}")
        else:
            log.info(f"Unhandled Etsy event: {event_type}")

    return {"status": "ok"}


async def _handle_etsy_order_paid(db: AsyncSession, data: dict, shop_id: str):
    """Handle Etsy order.paid — log the sale for the connected user's dashboard."""
    # Find the user who owns this Etsy shop
    result = await db.execute(
        select(User).where(User.etsy_shop_id == shop_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        log.warning(f"Etsy order.paid: no user found for shop {shop_id}")
        return

    # The resource_url contains the receipt endpoint — we could fetch details
    # but for now we just log the event for the dashboard
    resource_url = data.get("resource_url", "")
    log.info(f"Etsy sale for user {user.username} (shop {shop_id}): {resource_url}")

    # Note: To sync full order details, you'd fetch the receipt from:
    #   GET {resource_url} with the user's access token
    # For now we log the event — full receipt sync can be added later.


async def _handle_etsy_order_canceled(db: AsyncSession, data: dict, shop_id: str):
    """Handle Etsy order.canceled — log the cancellation."""
    result = await db.execute(
        select(User).where(User.etsy_shop_id == shop_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        return

    log.info(f"Etsy order canceled for user {user.username} (shop {shop_id})")
