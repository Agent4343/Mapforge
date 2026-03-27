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
from app.models.db_models import User, Purchase, MarketplaceListing, DesignCredit, PublishedListing, EtsyPurchase
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


# =============================================================================
# Etsy Webhooks
# =============================================================================

def _verify_etsy_signature(payload: bytes, headers: dict) -> bool:
    """Verify Etsy webhook signature using HMAC-SHA256.

    Implements Svix signature verification (the protocol Etsy uses):

      signed_content = <webhook-id> + "." + <webhook-timestamp> + "." + <raw_body_bytes>
      secret_bytes   = base64_decode(secret_after_"whsec_"_prefix)
      expected_sig   = base64_encode(HMAC_SHA256(secret_bytes, signed_content))

    Raw payload bytes are used directly instead of decoding to a string to
    avoid any byte-sequence transformation that would break the HMAC.
    """
    secret = settings.ETSY_WEBHOOK_SECRET
    if not secret:
        log.warning("ETSY_WEBHOOK_SECRET not set — rejecting webhook (configure secret to enable)")
        return False

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

    # Build signed content using raw bytes to avoid any encoding transformation.
    # Format: "<webhook-id>.<webhook-timestamp>.<raw_body>"
    signed_prefix = f"{webhook_id}.{webhook_timestamp}.".encode("utf-8")
    signed_content: bytes = signed_prefix + payload
    expected = base64.b64encode(
        hmac.new(secret_bytes, signed_content, hashlib.sha256).digest()
    ).decode("ascii")

    # Compare against all signatures in the header (space-separated).
    # Signatures may carry a version prefix like "v1,".
    for sig in webhook_signature.split(" "):
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
    """Handle Etsy order.paid — fulfil both DesignCredit and EtsyPurchase orders.

    Two flows are handled:
    1. *Legacy / post-purchase design*: the buyer bought a generic listing;
       we create a DesignCredit so they can design later. Idempotent on
       (etsy_receipt_id, etsy_shop_id).
    2. *Pre-purchase design (push-to-Etsy)*: the listing was created from a
       BuildDraft via ``POST /api/v1/etsy/push``.  We look up the
       PublishedListing by etsy_listing_id and create an EtsyPurchase
       idempotently using etsy_transaction_id.
    """
    import secrets

    # Find the seller (your account) who owns this Etsy shop
    result = await db.execute(
        select(User).where(User.etsy_shop_id == shop_id)
    )
    seller = result.scalar_one_or_none()
    if not seller:
        log.warning(f"Etsy order.paid: no user found for shop {shop_id}")
        return

    # Extract order details from the webhook payload
    receipt_id = str(data.get("receipt_id", data.get("resource_id", "")))
    buyer_email = data.get("buyer_email", "")

    # -----------------------------------------------------------------
    # Handle per-transaction line items for the push-to-Etsy flow.
    # Etsy sends a "transactions" list; each item has a listing_id.
    # -----------------------------------------------------------------
    transactions = data.get("transactions", [])
    for txn in transactions:
        txn_id = str(txn.get("transaction_id", ""))
        listing_id = str(txn.get("listing_id", ""))
        if not txn_id or not listing_id:
            continue

        # Look up whether this listing was pushed from a BuildDraft
        pub_result = await db.execute(
            select(PublishedListing).where(PublishedListing.etsy_listing_id == listing_id)
        )
        pub_listing = pub_result.scalar_one_or_none()
        if pub_listing is None:
            continue  # Not a push-to-Etsy listing; handled below

        # Idempotency: skip if we already have this transaction
        existing = await db.execute(
            select(EtsyPurchase).where(EtsyPurchase.etsy_transaction_id == txn_id)
        )
        if existing.scalar_one_or_none() is not None:
            log.info(f"EtsyPurchase for transaction {txn_id} already exists — skipping duplicate")
            continue

        purchase = EtsyPurchase(
            etsy_receipt_id=receipt_id,
            etsy_transaction_id=txn_id,
            published_listing_id=pub_listing.id,
            buyer_email=buyer_email,
            status="pending",
        )
        db.add(purchase)
        await db.flush()  # so purchase.id is assigned

        log.info(
            f"EtsyPurchase {purchase.id} created for transaction {txn_id} "
            f"(listing {listing_id}, receipt {receipt_id})"
        )

    await db.commit()

    # -----------------------------------------------------------------
    # Legacy flow: create DesignCredit for generic listings.
    # Skip if ALL transactions were accounted for by the push-to-Etsy path.
    # Idempotent on (etsy_receipt_id, etsy_shop_id).
    # -----------------------------------------------------------------
    # Check whether a credit already exists for this receipt
    existing_credit = await db.execute(
        select(DesignCredit).where(
            DesignCredit.etsy_receipt_id == receipt_id,
            DesignCredit.etsy_shop_id == shop_id,
        )
    )
    if existing_credit.scalar_one_or_none() is not None:
        log.info(f"DesignCredit for receipt {receipt_id} already exists — skipping duplicate")
        return

    listing_title = data.get("title", "")
    price_raw = data.get("grandtotal", data.get("subtotal", {}))
    price_cents = 0
    if isinstance(price_raw, dict):
        # Etsy sends price as {"amount": 1299, "divisor": 100, "currency_code": "USD"}
        price_cents = int(price_raw.get("amount", 0))
    elif isinstance(price_raw, (int, float)):
        price_cents = int(price_raw * 100)

    # Determine product type from listing title (basic heuristic)
    title_lower = (listing_title or "").lower()
    product_type = "lake"  # default
    for pt in ("province", "city", "park", "community", "name_sign"):
        if pt.replace("_", " ") in title_lower:
            product_type = pt
            break

    # Create the design credit
    token = secrets.token_urlsafe(32)
    credit = DesignCredit(
        etsy_receipt_id=receipt_id,
        etsy_shop_id=shop_id,
        etsy_buyer_email=buyer_email,
        seller_id=seller.id,
        product_type=product_type,
        etsy_listing_title=listing_title,
        price_cents=price_cents,
        redeem_token=token,
        status="unused",
    )
    db.add(credit)
    await db.commit()

    frontend_url = settings.FRONTEND_URL or "https://mapforge-production.up.railway.app"
    design_url = f"{frontend_url}?credit={token}"

    log.info(
        f"Design credit created for Etsy order {receipt_id} "
        f"(shop {shop_id}, buyer {buyer_email}): {design_url}"
    )

    # Send the design link to the buyer via Etsy message
    if seller.etsy_access_token and receipt_id:
        try:
            from app.services.etsy_client import send_buyer_message, get_valid_token
            from app.services.app_settings import get_etsy_credentials

            creds = await get_etsy_credentials(db)
            access_token = await get_valid_token(seller, creds=creds)
            await db.commit()  # persist any refreshed tokens

            message = (
                f"Thank you for your purchase! Here is your custom map design link:\n\n"
                f"{design_url}\n\n"
                f"Click the link above to:\n"
                f"1. Choose any location in the world\n"
                f"2. Customize colors, style, and text\n"
                f"3. Download your print-ready files\n\n"
                f"You can redesign up to 5 times. Enjoy!"
            )
            sent = await send_buyer_message(
                access_token=access_token,
                shop_id=shop_id,
                receipt_id=receipt_id,
                message=message,
                creds=creds,
            )
            if sent:
                log.info(f"Design link sent to buyer via Etsy message for receipt {receipt_id}")
            else:
                log.warning(f"Could not auto-send design link for receipt {receipt_id} — seller should send manually")
        except Exception as e:
            log.warning(f"Failed to send Etsy message for receipt {receipt_id}: {e}")


async def _handle_etsy_order_canceled(db: AsyncSession, data: dict, shop_id: str):
    """Handle Etsy order.canceled — log the cancellation."""
    result = await db.execute(
        select(User).where(User.etsy_shop_id == shop_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        return

    log.info(f"Etsy order canceled for user {user.username} (shop {shop_id})")
