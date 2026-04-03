"""Tests for admin settings endpoints."""

import pytest
from sqlalchemy import select

from app.models.db_models import User
from app.services.app_settings import set_setting


async def _register_admin(client, email: str = "admin@mapforge.dev"):
    resp = await client.post("/api/v1/auth/register", json={
        "email": email,
        "username": "adminuser",
        "password": "AdminPass123!",
    })
    assert resp.status_code == 201
    token = resp.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"


@pytest.mark.asyncio
async def test_admin_maptiler_settings_roundtrip(client, db_session, monkeypatch):
    monkeypatch.setattr("app.config.settings.ADMIN_EMAILS", ["admin@mapforge.dev"])
    await _register_admin(client)

    # Seed settings to validate read/masking.
    await set_setting(db_session, "MAPTILER_KEY", "abc1234567890")
    await set_setting(db_session, "MAPTILER_STATIC_STYLE", "backdrop")
    await set_setting(db_session, "MAPFORGE_MAPTILER_ONLY_MODE", "1")

    get_resp = await client.get("/api/v1/admin/maptiler-settings")
    assert get_resp.status_code == 200
    data = get_resp.json()
    assert data["configured"] is True
    assert data["api_key"].startswith("abc12345")
    assert data["api_key"].endswith("...")
    assert data["static_style"] == "backdrop"
    assert data["maptiler_only_mode"] is True

    save_resp = await client.post(
        "/api/v1/admin/maptiler-settings",
        json={
            "api_key": "new_maptiler_key",
            "static_style": "basic-v2",
            "maptiler_only_mode": True,
        },
    )
    assert save_resp.status_code == 200
    assert save_resp.json()["status"] == "saved"

    # Ensure both key aliases are updated for compatibility.
    from app.services.app_settings import get_setting
    assert await get_setting(db_session, "MAPTILER_KEY") == "new_maptiler_key"
    assert await get_setting(db_session, "VITE_MAPTILER_KEY") == "new_maptiler_key"
    assert await get_setting(db_session, "MAPTILER_STATIC_STYLE") == "basic-v2"
    assert await get_setting(db_session, "MAPFORGE_MAPTILER_ONLY_MODE") == "1"
    assert await get_setting(db_session, "MAPTILER_ONLY_MODE") == "1"

    clear_resp = await client.delete("/api/v1/admin/maptiler-settings")
    assert clear_resp.status_code == 200
    assert clear_resp.json()["status"] == "cleared"

    assert await get_setting(db_session, "MAPTILER_KEY") is None
    assert await get_setting(db_session, "VITE_MAPTILER_KEY") is None
    assert await get_setting(db_session, "MAPTILER_STATIC_STYLE") is None
    assert await get_setting(db_session, "MAPFORGE_MAPTILER_ONLY_MODE") is None
    assert await get_setting(db_session, "MAPTILER_ONLY_MODE") is None


@pytest.mark.asyncio
async def test_admin_maptiler_settings_requires_admin(client, db_session):
    from app.config import settings
    settings.ADMIN_EMAILS = ["admin@mapforge.dev"]
    # Self-registration is disabled for non-admin emails.
    resp = await client.post("/api/v1/auth/register", json={
        "email": "free@mapforge.dev",
        "username": "freeuser",
        "password": "FreePass123!",
    })
    assert resp.status_code == 403

    # Create a non-admin user directly to validate admin endpoint authz.
    from app.services.auth import hash_password
    free_user = User(
        email="free@mapforge.dev",
        username="freeuser",
        hashed_password=hash_password("FreePass123!"),
        tier="free",
    )
    db_session.add(free_user)
    await db_session.commit()

    login_resp = await client.post("/api/v1/auth/login", json={
        "email": "free@mapforge.dev",
        "password": "FreePass123!",
    })
    assert login_resp.status_code == 403

    # Use a forged token path from the auth service for endpoint checks.
    from app.services.auth import create_access_token
    token = create_access_token(free_user.id)
    client.headers["Authorization"] = f"Bearer {token}"

    # Confirm tier is free in DB.
    row = await db_session.execute(select(User).where(User.email == "free@mapforge.dev"))
    assert row.scalar_one().tier == "free"

    get_resp = await client.get("/api/v1/admin/maptiler-settings")
    assert get_resp.status_code == 403

    post_resp = await client.post("/api/v1/admin/maptiler-settings", json={"api_key": "x"})
    assert post_resp.status_code == 403

    del_resp = await client.delete("/api/v1/admin/maptiler-settings")
    assert del_resp.status_code == 403
