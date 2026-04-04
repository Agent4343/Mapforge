"""Regression tests for admin download endpoint behavior."""

import pytest

from app.models.db_models import GeneratedFile
from app.routers import generate as generate_router


async def _create_generated_file(db_session, **overrides) -> GeneratedFile:
    payload = {
        "owner_id": None,
        "osm_id": 390558,
        "osm_type": "relation",
        "product_type": "city",
        "location_name": "Halifax, Nova Scotia",
        "display_text": "Halifax",
        "board_size": "print_16x20",
        "board_width_mm": 406.4,
        "board_height_mm": 508.0,
        "style": "filled",
        "show_coordinates": True,
        "font_size_mm": 14.0,
        "node_count": 120,
        "path_count": 320,
        "layer_count": 8,
        "svg_storage_key": "svg/test.svg",
        "print_png_key": "print/test.png",
    }
    payload.update(overrides)
    file_record = GeneratedFile(
        **payload,
    )
    db_session.add(file_record)
    await db_session.commit()
    await db_session.refresh(file_record)
    return file_record


@pytest.mark.asyncio
async def test_admin_download_print_png_success(auth_client, db_session, monkeypatch):
    client, _user = auth_client
    generated = await _create_generated_file(db_session)

    async def _fake_retrieve(_key: str):
        return b"PNGDATA"

    monkeypatch.setattr(generate_router, "retrieve_file", _fake_retrieve)

    resp = await client.get(f"/api/v1/download/{generated.id}?format=png")
    assert resp.status_code == 200
    assert resp.content == b"PNGDATA"
    assert resp.headers["content-type"].startswith("image/png")


@pytest.mark.asyncio
async def test_admin_download_print_png_returns_503_on_storage_error(auth_client, db_session, monkeypatch):
    client, _user = auth_client
    generated = await _create_generated_file(db_session)

    async def _failing_retrieve(_key: str):
        raise RuntimeError("storage backend unavailable")

    monkeypatch.setattr(generate_router, "retrieve_file", _failing_retrieve)

    resp = await client.get(f"/api/v1/download/{generated.id}?format=png")
    assert resp.status_code == 503
    assert "temporarily unavailable" in resp.text.lower()


@pytest.mark.asyncio
async def test_admin_download_print_png_falls_back_to_svg_render(auth_client, db_session, monkeypatch):
    client, _user = auth_client
    generated = await _create_generated_file(
        db_session,
        print_png_key="print/missing.png",
        svg_storage_key="svg/fallback.svg",
    )

    async def _fake_retrieve(key: str):
        if key == "print/missing.png":
            return None
        if key == "svg/fallback.svg":
            return b"<svg xmlns='http://www.w3.org/2000/svg'></svg>"
        return None

    def _fake_generate_print_image(_svg: str, skip_remap: bool = True):
        return b"ONDEMANDPNG"

    monkeypatch.setattr(generate_router, "retrieve_file", _fake_retrieve)
    import app.services.thumbnail_generator as thumbnail_generator
    monkeypatch.setattr(thumbnail_generator, "generate_print_image", _fake_generate_print_image)

    resp = await client.get(f"/api/v1/download/{generated.id}?format=png")
    assert resp.status_code == 200
    assert resp.content == b"ONDEMANDPNG"
    assert resp.headers["content-type"].startswith("image/png")
