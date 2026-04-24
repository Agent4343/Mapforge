"""Regression tests for authorization gates on sensitive endpoints.

Covers the two gaps found in the admin/ownership audit:

  * `POST /api/v1/orders/credits/create` — must be admin-only.
    Any anonymous or non-admin caller able to mint a DesignCredit
    bypasses Etsy payment entirely.
  * `GET  /api/v1/preview/{file_id}` — must require auth AND
    ownership (or admin). Returns the raw unwatermarked SVG, i.e.
    the actual paid product.

Also re-asserts a few already-correct gates so a future regression
doesn't silently open them:

  * `/admin/stats` is admin-only.
  * `/library` requires auth.
"""

import pytest


# ─── /orders/credits/create ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_credits_create_rejects_anonymous(client):
    resp = await client.post("/api/v1/orders/credits/create")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_credits_create_rejects_regular_user(auth_client):
    http, _ = auth_client
    resp = await http.post("/api/v1/orders/credits/create")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_credits_create_allowed_for_admin(admin_client):
    http, _ = admin_client
    resp = await http.post(
        "/api/v1/orders/credits/create",
        params={"product_type": "lake", "product_tier": "standard"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "token" in data
    assert "design_url" in data
    assert len(data["token"]) >= 32  # secrets.token_urlsafe(32) output


# ─── /preview/{file_id} ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_preview_rejects_anonymous(client):
    """No auth at all → 401."""
    resp = await client.get("/api/v1/preview/fakeid1234567890")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_preview_rejects_non_owner(auth_client, db_session):
    """An authenticated user who doesn't own the file must 403, not
    404 — a 404 would leak file-id existence to probe for it, but
    we'd rather take the tradeoff here so owners see a clear error
    when their own file is missing."""
    from app.models.db_models import GeneratedFile

    http, me = auth_client

    # Plant a file owned by a DIFFERENT synthetic user id.
    file = GeneratedFile(
        id="otherfileid01234",
        owner_id="some-other-user-id",
        osm_id=1,
        osm_type="relation",
        product_type="lake",
        location_name="Other's Lake",
        display_text="Other's Lake",
        board_size="print_16x20",
        board_width_mm=406.4,
        board_height_mm=508.0,
        style="filled",
        svg_storage_key="svg/other.svg",
    )
    db_session.add(file)
    await db_session.commit()

    resp = await http.get(f"/api/v1/preview/{file.id}")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_preview_missing_file_returns_404(auth_client):
    http, _ = auth_client
    resp = await http.get("/api/v1/preview/does-not-exist")
    assert resp.status_code == 404


# ─── Already-correct gates (regression guards) ───────────────────────

@pytest.mark.asyncio
async def test_admin_stats_rejects_regular_user(auth_client):
    http, _ = auth_client
    resp = await http.get("/api/v1/admin/stats")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_stats_allowed_for_admin(admin_client):
    http, _ = admin_client
    resp = await http.get("/api/v1/admin/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_users" in data


@pytest.mark.asyncio
async def test_library_requires_auth(client):
    resp = await client.get("/api/v1/library")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_etsy_settings_rejects_regular_user(auth_client):
    """Etsy API keys are a revenue-sensitive credential — never let
    non-admins read them, even masked."""
    http, _ = auth_client
    resp = await http.get("/api/v1/admin/etsy-settings")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_marketplace_update_requires_ownership(auth_client, db_session):
    """A seller must not be able to update another seller's listing."""
    from app.models.db_models import GeneratedFile, MarketplaceListing

    http, me = auth_client

    # Plant a file + listing owned by someone else.
    file = GeneratedFile(
        id="otherfile2222222",
        owner_id="other-seller-id",
        osm_id=1,
        osm_type="relation",
        product_type="lake",
        location_name="Other Lake",
        display_text="Other Lake",
        board_size="print_16x20",
        board_width_mm=406.4,
        board_height_mm=508.0,
        style="filled",
        svg_storage_key="svg/other2.svg",
    )
    listing = MarketplaceListing(
        id="otherlisting3333",
        file_id=file.id,
        seller_id="other-seller-id",
        price_cents=1999,
        title="Someone Else's Listing",
    )
    db_session.add_all([file, listing])
    await db_session.commit()

    resp = await http.patch(
        f"/api/v1/marketplace/{listing.id}",
        json={"price_cents": 500},  # valid per schema (min 199)
    )
    # 404 is also acceptable here — the query filters on
    # `seller_id == user.id` so the row is invisible. Either
    # way, the update MUST NOT succeed.
    assert resp.status_code in (403, 404)

    # Verify the price wasn't touched.
    await db_session.refresh(listing)
    assert listing.price_cents == 1999
