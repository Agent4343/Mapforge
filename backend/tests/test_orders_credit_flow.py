"""Tests for Etsy design-credit flow behavior."""

import pytest
from sqlalchemy import select

from app.models.db_models import DesignCredit, GeneratedFile


@pytest.mark.asyncio
async def test_credit_download_is_one_time_and_unlinks_file(client, db_session, monkeypatch):
    # Create completed credit + generated file record.
    gen = GeneratedFile(
        owner_id=None,
        osm_id=390558,
        osm_type="relation",
        product_type="city",
        location_name="Halifax",
        display_text="Halifax",
        board_size="print_16x20",
        board_width_mm=406.4,
        board_height_mm=508.0,
        style="filled",
        show_coordinates=True,
        font_size_mm=14.0,
        node_count=100,
        path_count=200,
        layer_count=8,
        svg_storage_key="svg/test.svg",
        print_png_key="print/test.png",
    )
    db_session.add(gen)
    await db_session.commit()
    await db_session.refresh(gen)

    credit = DesignCredit(
        redeem_token="tok_one_time",
        status="completed",
        product_type="city",
        file_id=gen.id,
        max_downloads=1,
    )
    db_session.add(credit)
    await db_session.commit()

    # Monkeypatch storage read/delete so we don't need real files.
    from app.routers import orders as orders_router

    from tests.conftest import TestSession
    monkeypatch.setattr(orders_router, "async_session", TestSession)

    deleted_keys = []

    async def _fake_retrieve(_key: str):
        return b"PNGDATA"

    async def _fake_delete(key: str):
        deleted_keys.append(key)
        return True

    from app.services import file_storage as fs

    monkeypatch.setattr(fs, "retrieve_file", _fake_retrieve)
    monkeypatch.setattr(fs, "delete_file", _fake_delete)
    first = await client.get("/api/v1/orders/download/tok_one_time?format=png")
    assert first.status_code == 200
    assert first.content == b"PNGDATA"

    # Second attempt should fail (already downloaded once).
    second = await client.get("/api/v1/orders/download/tok_one_time?format=png")
    assert second.status_code == 410

    # Verify persisted state using a fresh session (download endpoint uses a
    # separate DB session, so original fixture session may have stale identity map).
    async with TestSession() as verify_db:
        refreshed = await verify_db.execute(
            select(DesignCredit).where(DesignCredit.redeem_token == "tok_one_time")
        )
        c = refreshed.scalar_one()
        assert c.download_count == 1
        assert c.status == "downloaded"
        assert c.file_id is None

        refreshed_file = await verify_db.execute(
            select(GeneratedFile).where(GeneratedFile.id == gen.id)
        )
        gf = refreshed_file.scalar_one()
        assert gf.print_png_key is None
        assert gf.thumbnail_key is None
        assert gf.dxf_storage_key is None
        assert gf.svg_storage_key.startswith("deleted/")
        assert deleted_keys
