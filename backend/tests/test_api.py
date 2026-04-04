"""Tests for API endpoints (health, root)."""

import pytest
from app.services.app_settings import set_setting


@pytest.mark.asyncio
async def test_root(client):
    resp = await client.get("/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["app"] == "MapForge CNC"
    assert data["version"] == "1.0.0"


@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_public_config_exposes_maptiler_key_from_settings(client, db_session):
    await set_setting(db_session, "MAPTILER_KEY", "abc123")
    resp = await client.get("/api/v1/config")
    assert resp.status_code == 200
    data = resp.json()
    assert "maptiler_key" in data
    assert data["maptiler_key"] == "abc123"


@pytest.mark.asyncio
async def test_public_config_exposes_runtime_settings(client):
    resp = await client.get("/api/v1/config")
    assert resp.status_code == 200
    data = resp.json()
    assert "etsy_shop_url" in data
    assert "maptiler_key" in data
    assert "maptiler_only_mode" in data


@pytest.mark.asyncio
async def test_public_config_maptiler_mode_can_be_enabled_from_db(client, db_session):
    await set_setting(db_session, "MAPFORGE_MAPTILER_ONLY_MODE", "1")
    resp = await client.get("/api/v1/config")
    assert resp.status_code == 200
    data = resp.json()
    assert data["maptiler_only_mode"] is True


def test_maptiler_mode_parser_accepts_quoted_truthy(monkeypatch):
    monkeypatch.setenv("MAPFORGE_MAPTILER_ONLY_MODE", '"true"')
    monkeypatch.delenv("MAPTILER_ONLY_MODE", raising=False)
    from app.config import _parse_env_bool  # local import to avoid module-order side effects
    assert _parse_env_bool('"true"') is True


def test_first_non_empty_env_prefers_legacy_when_primary_blank(monkeypatch):
    monkeypatch.setenv("MAPFORGE_MAPTILER_ONLY_MODE", " ")
    monkeypatch.setenv("MAPTILER_ONLY_MODE", "1")
    from app.config import _first_non_empty_env
    assert _first_non_empty_env("MAPFORGE_MAPTILER_ONLY_MODE", "MAPTILER_ONLY_MODE") == "1"


@pytest.mark.asyncio
async def test_library_requires_auth(client):
    resp = await client.get("/api/v1/library")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_marketplace_browse_public(client):
    resp = await client.get("/api/v1/marketplace")
    assert resp.status_code == 200
    data = resp.json()
    assert "listings" in data
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_marketplace_dashboard_requires_auth(client):
    resp = await client.get("/api/v1/marketplace/dashboard")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_library_empty_for_new_user(auth_client):
    client, user = auth_client
    resp = await client.get("/api/v1/library")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["files"] == []
