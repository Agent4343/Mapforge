"""Stripe payment integration for marketplace and subscriptions."""

import stripe
from fastapi import HTTPException

from app.config import settings
from app.logging_config import log

stripe.api_key = settings.STRIPE_SECRET_KEY

SUBSCRIPTION_PRICES = {
    "maker_monthly": "price_maker_monthly",  # Set via env/Stripe dashboard
    "maker_annual": "price_maker_annual",
    "pro_monthly": "price_pro_monthly",
    "pro_annual": "price_pro_annual",
}


async def create_customer(email: str, name: str) -> str:
    """Create a Stripe customer. Returns customer ID."""
    if not settings.STRIPE_SECRET_KEY:
        log.warning("Stripe not configured — returning mock customer ID")
        return f"cus_mock_{email.split('@')[0]}"

    customer = stripe.Customer.create(email=email, name=name)
    log.info(f"Created Stripe customer: {customer.id}")
    return customer.id


async def create_checkout_session(
    customer_id: str,
    price_id: str,
    success_url: str,
    cancel_url: str,
) -> str:
    """Create a Stripe Checkout session for subscription. Returns session URL."""
    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(status_code=503, detail="Payments not configured")

    session = stripe.checkout.Session.create(
        customer=customer_id,
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=success_url,
        cancel_url=cancel_url,
    )
    return session.url


async def create_payment_intent(
    customer_id: str,
    amount_cents: int,
    currency: str = "usd",
    metadata: dict | None = None,
) -> dict:
    """Create a payment intent for a marketplace purchase."""
    if not settings.STRIPE_SECRET_KEY:
        log.warning("Stripe not configured — returning mock payment intent")
        return {
            "id": "pi_mock_" + str(amount_cents),
            "client_secret": "mock_secret",
            "status": "succeeded",
        }

    intent = stripe.PaymentIntent.create(
        amount=amount_cents,
        currency=currency,
        customer=customer_id,
        metadata=metadata or {},
        automatic_payment_methods={"enabled": True},
    )
    return {
        "id": intent.id,
        "client_secret": intent.client_secret,
        "status": intent.status,
    }


async def create_transfer(
    amount_cents: int,
    destination_account: str,
    transfer_group: str | None = None,
) -> str | None:
    """Transfer funds to a seller's connected account."""
    if not settings.STRIPE_SECRET_KEY:
        return None

    transfer = stripe.Transfer.create(
        amount=amount_cents,
        currency="usd",
        destination=destination_account,
        transfer_group=transfer_group,
    )
    return transfer.id


def verify_webhook_signature(payload: bytes, sig_header: str) -> dict:
    """Verify and parse a Stripe webhook event."""
    if not settings.STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="Webhook secret not configured")

    event = stripe.Webhook.construct_event(
        payload, sig_header, settings.STRIPE_WEBHOOK_SECRET,
    )
    return event
