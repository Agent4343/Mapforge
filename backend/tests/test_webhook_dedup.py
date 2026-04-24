"""Tests for webhook idempotency (`_claim_webhook` + the WebhookEvent table).

These guard the exactly-once semantics on the Etsy and Stripe
webhook endpoints. If a replay ever succeeds in running side
effects a second time, a single Etsy `order.paid` delivery could
grant a buyer two design credits.
"""

import pytest

from app.models.db_models import WebhookEvent
from app.routers.webhooks import _claim_webhook


@pytest.mark.asyncio
async def test_first_claim_succeeds(db_session):
    ok = await _claim_webhook(db_session, "etsy", "evt_001", "order.paid")
    assert ok is True
    await db_session.commit()


@pytest.mark.asyncio
async def test_replay_is_deduplicated(db_session):
    first = await _claim_webhook(db_session, "etsy", "evt_001", "order.paid")
    assert first is True
    await db_session.commit()

    second = await _claim_webhook(db_session, "etsy", "evt_001", "order.paid")
    assert second is False, "replay with same (source, event_id) should dedup"


@pytest.mark.asyncio
async def test_different_event_id_claims(db_session):
    await _claim_webhook(db_session, "etsy", "evt_A", "order.paid")
    await db_session.commit()

    ok = await _claim_webhook(db_session, "etsy", "evt_B", "order.paid")
    assert ok is True


@pytest.mark.asyncio
async def test_same_id_different_source_claims(db_session):
    """Etsy and Stripe happen to hand out numeric ids — they must not collide."""
    await _claim_webhook(db_session, "etsy", "1", "order.paid")
    await db_session.commit()

    ok = await _claim_webhook(db_session, "stripe", "1", "payment_intent.succeeded")
    assert ok is True


@pytest.mark.asyncio
async def test_claim_persists_row(db_session):
    from sqlalchemy import select

    await _claim_webhook(db_session, "etsy", "evt_persist", "order.paid")
    await db_session.commit()

    result = await db_session.execute(
        select(WebhookEvent).where(
            WebhookEvent.source == "etsy", WebhookEvent.event_id == "evt_persist"
        )
    )
    row = result.scalar_one_or_none()
    assert row is not None
    assert row.event_type == "order.paid"
