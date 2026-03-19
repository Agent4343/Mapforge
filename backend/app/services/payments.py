"""Stripe payment integration for marketplace, subscriptions, and seller payouts."""

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


def _require_stripe(operation: str = "This operation"):
    """Raise 503 if Stripe is not configured."""
    if not settings.STRIPE_SECRET_KEY:
        if settings.is_production:
            log.error(f"Stripe not configured in production — {operation} blocked")
            raise HTTPException(
                status_code=503,
                detail="Payment system is not configured. Please contact support.",
            )
        log.warning(f"Stripe not configured — {operation} skipped (dev mode)")
        return False
    return True


async def create_customer(email: str, name: str) -> str:
    """Create a Stripe customer. Returns customer ID."""
    if not _require_stripe("customer creation"):
        return f"cus_dev_{email.split('@')[0]}"

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
    _require_stripe("checkout session")

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
    transfer_group: str | None = None,
) -> dict:
    """Create a payment intent for a marketplace purchase."""
    if not _require_stripe("payment intent"):
        return {
            "id": "pi_dev_" + str(amount_cents),
            "client_secret": "dev_secret",
            "status": "succeeded",
        }

    params = {
        "amount": amount_cents,
        "currency": currency,
        "customer": customer_id,
        "metadata": metadata or {},
        "automatic_payment_methods": {"enabled": True},
    }
    if transfer_group:
        params["transfer_group"] = transfer_group

    intent = stripe.PaymentIntent.create(**params)
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
    if not _require_stripe("transfer"):
        return None

    transfer = stripe.Transfer.create(
        amount=amount_cents,
        currency="usd",
        destination=destination_account,
        transfer_group=transfer_group,
    )
    return transfer.id


# --- Connected Accounts for Seller Payouts ---

async def create_connected_account(email: str, country: str = "CA") -> str:
    """Create a Stripe Connect Express account for a seller."""
    if not _require_stripe("connected account"):
        return f"acct_dev_{email.split('@')[0]}"

    account = stripe.Account.create(
        type="express",
        country=country,
        email=email,
        capabilities={
            "transfers": {"requested": True},
        },
    )
    log.info(f"Created Stripe connected account: {account.id}")
    return account.id


async def create_account_onboarding_link(
    account_id: str,
    refresh_url: str,
    return_url: str,
) -> str:
    """Create an onboarding link for a seller to complete Stripe setup."""
    _require_stripe("account onboarding")

    link = stripe.AccountLink.create(
        account=account_id,
        refresh_url=refresh_url,
        return_url=return_url,
        type="account_onboarding",
    )
    return link.url


async def get_account_status(account_id: str) -> dict:
    """Check the status of a connected account."""
    if not _require_stripe("account status check"):
        return {"charges_enabled": False, "payouts_enabled": False, "details_submitted": False}

    account = stripe.Account.retrieve(account_id)
    return {
        "charges_enabled": account.charges_enabled,
        "payouts_enabled": account.payouts_enabled,
        "details_submitted": account.details_submitted,
    }


async def create_payout(
    amount_cents: int,
    destination_account: str,
    description: str = "MapForge marketplace payout",
) -> str | None:
    """Create a payout to a seller's connected account bank."""
    if not _require_stripe("payout"):
        return None

    try:
        payout = stripe.Payout.create(
            amount=amount_cents,
            currency="usd",
            description=description,
            stripe_account=destination_account,
        )
        return payout.id
    except stripe.error.StripeError as e:
        log.error(f"Payout failed for {destination_account}: {e}")
        return None


def verify_webhook_signature(payload: bytes, sig_header: str) -> dict:
    """Verify and parse a Stripe webhook event."""
    if not settings.STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="Webhook secret not configured")

    event = stripe.Webhook.construct_event(
        payload, sig_header, settings.STRIPE_WEBHOOK_SECRET,
    )
    return event
