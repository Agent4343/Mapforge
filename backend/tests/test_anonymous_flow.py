"""Tests for the anonymous map builder → push-to-Etsy → fulfilment pipeline.

Covers:
- BuildDraft CRUD endpoints
- Idempotent EtsyPurchase creation from webhook payload
- Mapping listing_id → PublishedListing
- Generation persistence for anonymous context (persist_anonymous=True)
"""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from app.models.db_models import (
    BuildDraft,
    EtsyPurchase,
    GeneratedFile,
    PublishedListing,
    User,
)


# ---------------------------------------------------------------------------
# BuildDraft endpoints
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_draft(client):
    """POST /api/v1/drafts creates a draft and returns a token."""
    resp = await client.post("/api/v1/drafts", json={
        "design_config": {"osm_id": 123, "product_type": "lake"},
    })
    assert resp.status_code == 201
    data = resp.json()
    assert "draft_token" in data
    assert data["design_config"] == {"osm_id": 123, "product_type": "lake"}
    assert data["expires_at"] is not None


@pytest.mark.asyncio
async def test_get_draft(client):
    """GET /api/v1/drafts/{token} returns the stored draft."""
    create_resp = await client.post("/api/v1/drafts", json={
        "design_config": {"test": True},
    })
    token = create_resp.json()["draft_token"]

    get_resp = await client.get(f"/api/v1/drafts/{token}")
    assert get_resp.status_code == 200
    assert get_resp.json()["draft_token"] == token
    assert get_resp.json()["design_config"] == {"test": True}


@pytest.mark.asyncio
async def test_get_draft_not_found(client):
    """GET /api/v1/drafts/{token} returns 404 for unknown token."""
    resp = await client.get("/api/v1/drafts/no-such-token")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_draft(client):
    """PATCH /api/v1/drafts/{token} updates design_config."""
    create_resp = await client.post("/api/v1/drafts", json={
        "design_config": {"v": 1},
    })
    token = create_resp.json()["draft_token"]

    patch_resp = await client.patch(f"/api/v1/drafts/{token}", json={
        "design_config": {"v": 2, "extra": "field"},
    })
    assert patch_resp.status_code == 200
    assert patch_resp.json()["design_config"]["v"] == 2


@pytest.mark.asyncio
async def test_create_draft_empty(client):
    """POST /api/v1/drafts with no config still creates a draft."""
    resp = await client.post("/api/v1/drafts", json={})
    assert resp.status_code == 201
    assert resp.json()["design_config"] is None


# ---------------------------------------------------------------------------
# Idempotent EtsyPurchase creation via webhook
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_etsy_purchase_idempotency(db_session):
    """Inserting an EtsyPurchase with a duplicate etsy_transaction_id fails.

    The unique constraint on etsy_transaction_id is the database-level guard
    that prevents duplicate purchases from webhook retries.
    """
    from sqlalchemy.exc import IntegrityError

    draft = BuildDraft(
        draft_token="test-idem-token",
        design_config=json.dumps({"osm_id": 1}),
    )
    db_session.add(draft)
    await db_session.flush()

    pub = PublishedListing(
        etsy_listing_id="9999001",
        build_draft_id=draft.id,
        listing_url="https://etsy.com/listing/9999001",
        state="draft",
        status="active",
    )
    db_session.add(pub)
    await db_session.flush()

    purchase1 = EtsyPurchase(
        etsy_receipt_id="rcpt-001",
        etsy_transaction_id="txn-unique-001",
        published_listing_id=pub.id,
        status="pending",
    )
    db_session.add(purchase1)
    await db_session.commit()

    # Attempt to insert a second purchase with the same transaction ID
    purchase2 = EtsyPurchase(
        etsy_receipt_id="rcpt-002",
        etsy_transaction_id="txn-unique-001",  # duplicate!
        published_listing_id=pub.id,
        status="pending",
    )
    db_session.add(purchase2)
    with pytest.raises(IntegrityError):
        await db_session.flush()

    await db_session.rollback()


@pytest.mark.asyncio
async def test_webhook_handler_creates_etsy_purchase(db_session):
    """_handle_etsy_order_paid creates an EtsyPurchase for a push-to-Etsy listing."""
    from sqlalchemy import select
    from app.routers.webhooks import _handle_etsy_order_paid

    # Create a seller with a connected Etsy shop
    seller = User(
        email="seller@example.com",
        username="seller",
        hashed_password="x",
        etsy_shop_id="shop-42",
        etsy_access_token="tok",
    )
    db_session.add(seller)
    await db_session.flush()

    # Create a BuildDraft + PublishedListing (push-to-Etsy flow)
    draft = BuildDraft(
        draft_token="draft-webhook-test",
        design_config=json.dumps({"osm_id": 55, "product_type": "city"}),
    )
    db_session.add(draft)
    await db_session.flush()

    pub = PublishedListing(
        etsy_listing_id="7654321",
        build_draft_id=draft.id,
        listing_url="https://etsy.com/listing/7654321",
        state="draft",
        status="active",
    )
    db_session.add(pub)
    await db_session.commit()

    # Simulate webhook payload containing the listing
    data = {
        "receipt_id": "rcpt-9001",
        "buyer_email": "buyer@example.com",
        "transactions": [
            {"transaction_id": "txn-9001", "listing_id": "7654321"},
        ],
    }

    # Suppress the seller message send (needs real Etsy token)
    with patch("app.routers.webhooks.settings") as mock_settings:
        mock_settings.FRONTEND_URL = "http://localhost:5173"
        mock_settings.ETSY_WEBHOOK_SECRET = None  # not needed for this call
        await _handle_etsy_order_paid(db_session, data, shop_id="shop-42")

    # Verify EtsyPurchase was created
    result = await db_session.execute(
        select(EtsyPurchase).where(EtsyPurchase.etsy_transaction_id == "txn-9001")
    )
    purchase = result.scalar_one_or_none()
    assert purchase is not None
    assert purchase.published_listing_id == pub.id
    assert purchase.etsy_receipt_id == "rcpt-9001"
    assert purchase.status == "pending"


@pytest.mark.asyncio
async def test_webhook_handler_idempotent(db_session):
    """_handle_etsy_order_paid is idempotent — same receipt creates only one DesignCredit."""
    from sqlalchemy import select
    from app.routers.webhooks import _handle_etsy_order_paid

    seller = User(
        email="seller2@example.com",
        username="seller2",
        hashed_password="x",
        etsy_shop_id="shop-99",
        etsy_access_token="tok",
    )
    db_session.add(seller)
    await db_session.commit()

    data = {
        "receipt_id": "rcpt-idem-42",
        "buyer_email": "buyer@example.com",
        "transactions": [],  # no push-to-Etsy transactions
        "title": "Custom Lake Map",
    }

    with patch("app.routers.webhooks.settings") as mock_settings:
        mock_settings.FRONTEND_URL = "http://localhost:5173"
        mock_settings.ETSY_WEBHOOK_SECRET = None
        await _handle_etsy_order_paid(db_session, data, shop_id="shop-99")
        await _handle_etsy_order_paid(db_session, data, shop_id="shop-99")  # second call

    from app.models.db_models import DesignCredit
    result = await db_session.execute(
        select(DesignCredit).where(
            DesignCredit.etsy_receipt_id == "rcpt-idem-42",
            DesignCredit.etsy_shop_id == "shop-99",
        )
    )
    credits = result.scalars().all()
    assert len(credits) == 1, "Idempotent: only one DesignCredit should exist"


# ---------------------------------------------------------------------------
# Listing ID → PublishedListing mapping
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_listing_id_maps_to_published_listing(db_session):
    """PublishedListing.etsy_listing_id can be used to locate the draft."""
    from sqlalchemy import select

    draft = BuildDraft(
        draft_token="map-tok",
        design_config=json.dumps({"osm_id": 77}),
    )
    db_session.add(draft)
    await db_session.flush()

    pub = PublishedListing(
        etsy_listing_id="ETL-5555",
        build_draft_id=draft.id,
        listing_url="https://etsy.com/listing/ETL-5555",
        state="active",
        status="active",
    )
    db_session.add(pub)
    await db_session.commit()

    result = await db_session.execute(
        select(PublishedListing).where(PublishedListing.etsy_listing_id == "ETL-5555")
    )
    found = result.scalar_one_or_none()
    assert found is not None
    assert found.build_draft_id == draft.id

    # And we can reach the design config through the relationship
    draft_result = await db_session.execute(
        select(BuildDraft).where(BuildDraft.id == found.build_draft_id)
    )
    found_draft = draft_result.scalar_one()
    assert json.loads(found_draft.design_config) == {"osm_id": 77}


# ---------------------------------------------------------------------------
# Anonymous generation persistence
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_do_generate_persist_anonymous(db_session):
    """_do_generate with persist_anonymous=True creates a GeneratedFile with owner_id=None."""
    from unittest.mock import AsyncMock, patch
    from sqlalchemy import select
    from app.routers.generate import _do_generate
    from app.models.schemas import GenerateRequest

    req = GenerateRequest(
        osm_id=12345,
        osm_type="relation",
        product_type="lake",
        text="Test Lake",
        board_size="print_8x10",
    )

    # Create a mock geometry object with the .bounds attribute shapely provides
    mock_geom = MagicMock()
    mock_geom.bounds = (-80.0, 44.0, -79.0, 45.0)  # (minx, miny, maxx, maxy)

    mock_processed = {
        "paths": [],
        "bounds": (-80, 44, -79, 45),
        "center_latlon": (44.5, -79.5),
        "transformed_bounds": (0, 0, 1000, 800),
        "board_mm": (203.2, 254.0),  # 8x10 inches in mm
    }
    mock_result = {
        "svg": "<svg/>",
        "node_count": 10,
        "path_count": 5,
        "layer_count": 2,
    }

    with (
        patch("app.routers.generate.fetch_geometry", new_callable=AsyncMock, return_value=mock_geom),
        patch("app.routers.generate.process_geometry", return_value=mock_processed),
        patch("app.routers.generate.transform_wgs84_to_board", return_value=mock_processed),
        patch("app.routers.generate.fetch_streets", new_callable=AsyncMock, return_value={}),
        patch("app.routers.generate.fetch_water_features", new_callable=AsyncMock, return_value={}),
        patch("app.routers.generate.fetch_contour_lines", new_callable=AsyncMock, return_value=[]),
        patch("app.routers.generate.generate_depth_bands", return_value=[]),
        patch("app.routers.generate.generate_svg", return_value=mock_result),
        patch("app.routers.generate.generate_thumbnail", return_value=b"\x89PNG"),
        patch("app.routers.generate.generate_print_image", return_value=b"\x89PNG"),
        patch("app.routers.generate.generate_etsy_listing_image", return_value=b"\x89PNG"),
        patch("app.routers.generate.store_file", new_callable=AsyncMock, side_effect=lambda key, *a, **kw: key),
    ):
        response = await _do_generate(req, user=None, db=db_session, persist_anonymous=True)

    assert response.file_id is not None, "file_id should be set when persist_anonymous=True"

    # Verify the DB record was created with owner_id=None
    result = await db_session.execute(
        select(GeneratedFile).where(GeneratedFile.id == response.file_id)
    )
    gen_file = result.scalar_one_or_none()
    assert gen_file is not None
    assert gen_file.owner_id is None  # anonymous — no user attached


@pytest.mark.asyncio
async def test_do_generate_visitor_no_persist(db_session):
    """_do_generate with user=None and persist_anonymous=False (default) does NOT persist."""
    from unittest.mock import AsyncMock, patch
    from sqlalchemy import select
    from app.routers.generate import _do_generate
    from app.models.schemas import GenerateRequest

    req = GenerateRequest(
        osm_id=99999,
        osm_type="relation",
        product_type="lake",
        text="Visitor Lake",
        board_size="print_8x10",
    )

    mock_geom = MagicMock()
    mock_geom.bounds = (-80.0, 44.0, -79.0, 45.0)

    mock_processed = {
        "paths": [],
        "bounds": (-80, 44, -79, 45),
        "center_latlon": (44.5, -79.5),
        "transformed_bounds": (0, 0, 1000, 800),
        "board_mm": (203.2, 254.0),
    }
    mock_result = {
        "svg": "<svg/>",
        "node_count": 1,
        "path_count": 1,
        "layer_count": 1,
    }

    with (
        patch("app.routers.generate.fetch_geometry", new_callable=AsyncMock, return_value=mock_geom),
        patch("app.routers.generate.process_geometry", return_value=mock_processed),
        patch("app.routers.generate.transform_wgs84_to_board", return_value=mock_processed),
        patch("app.routers.generate.fetch_streets", new_callable=AsyncMock, return_value={}),
        patch("app.routers.generate.fetch_water_features", new_callable=AsyncMock, return_value={}),
        patch("app.routers.generate.fetch_contour_lines", new_callable=AsyncMock, return_value=[]),
        patch("app.routers.generate.generate_depth_bands", return_value=[]),
        patch("app.routers.generate.generate_svg", return_value=mock_result),
        patch("app.routers.generate.generate_thumbnail", return_value=b"\x89PNG"),
        patch("app.routers.generate.generate_print_image", return_value=b"\x89PNG"),
        patch("app.routers.generate.generate_etsy_listing_image", return_value=b"\x89PNG"),
        patch("app.routers.generate.store_file", new_callable=AsyncMock, side_effect=lambda key, *a, **kw: key),
    ):
        response = await _do_generate(req, user=None, db=db_session, persist_anonymous=False)

    # No file_id should be returned in visitor preview mode
    assert response.file_id is None

    # Confirm no GeneratedFile was written for osm_id=99999
    result = await db_session.execute(
        select(GeneratedFile).where(GeneratedFile.osm_id == 99999)
    )
    assert result.scalar_one_or_none() is None
