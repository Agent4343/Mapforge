"""Tests for the HttpOnly session-cookie auth flow.

Guards the three properties we promised in the refactor:
  1. Login / register set BOTH the HttpOnly `mapforge_session`
     cookie and the JS-readable `mapforge_session_hint=1` cookie.
  2. `get_current_user` accepts the cookie (no Bearer required).
  3. `logout` clears both cookies.
"""

import pytest


async def _register(client, email="cookie@test.com", username="cookieuser"):
    return await client.post(
        "/api/v1/auth/register",
        json={"email": email, "username": username, "password": "SecurePass1!"},
    )


def _get_set_cookies(resp) -> dict[str, dict]:
    """Parse `Set-Cookie` headers into {name: {value, flags...}}."""
    out = {}
    for raw in resp.headers.get_list("set-cookie"):
        name, _, rest = raw.partition("=")
        value, _, attrs = rest.partition(";")
        flags = {"value": value}
        for chunk in attrs.split(";"):
            chunk = chunk.strip()
            if not chunk:
                continue
            if "=" in chunk:
                k, _, v = chunk.partition("=")
                flags[k.strip().lower()] = v.strip()
            else:
                flags[chunk.lower()] = True
        out[name.strip()] = flags
    return out


@pytest.mark.asyncio
async def test_register_sets_both_cookies(client):
    resp = await _register(client)
    assert resp.status_code == 201
    cookies = _get_set_cookies(resp)

    # HttpOnly session cookie carrying the JWT.
    assert "mapforge_session" in cookies
    session = cookies["mapforge_session"]
    assert session["value"]  # non-empty
    assert session.get("httponly") is True
    assert session.get("samesite", "").lower() == "strict"
    assert session.get("path") == "/"

    # Companion hint cookie, readable by JS for UI gating.
    assert "mapforge_session_hint" in cookies
    hint = cookies["mapforge_session_hint"]
    assert hint["value"] == "1"
    # Hint cookie must NOT be HttpOnly — the whole point is JS can read it.
    assert hint.get("httponly") is not True


@pytest.mark.asyncio
async def test_login_sets_cookies(client):
    await _register(client, email="login@test.com", username="loginu")
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "login@test.com", "password": "SecurePass1!"},
    )
    assert resp.status_code == 200
    cookies = _get_set_cookies(resp)
    assert "mapforge_session" in cookies
    assert "mapforge_session_hint" in cookies


@pytest.mark.asyncio
async def test_cookie_alone_authenticates_me(client):
    """After register, /auth/me must work on the cookie alone —
    without any Authorization header."""
    resp = await _register(client, email="cookie-only@test.com", username="cookieonly")
    assert resp.status_code == 201

    # httpx's AsyncClient already holds the cookies from the register
    # response; strip any Authorization header that might have been
    # set elsewhere to make sure we're testing the cookie path.
    client.headers.pop("authorization", None)
    me = await client.get("/api/v1/auth/me")
    assert me.status_code == 200
    data = me.json()
    assert data["email"] == "cookie-only@test.com"


@pytest.mark.asyncio
async def test_logout_clears_both_cookies(client):
    await _register(client, email="logout@test.com", username="logoutu")
    resp = await client.post("/api/v1/auth/logout")
    assert resp.status_code == 204

    cookies = _get_set_cookies(resp)
    # `delete_cookie` sets Max-Age=0 (or expires in the past). Assert
    # the headers are present — that's what tells the browser to drop.
    assert "mapforge_session" in cookies
    assert "mapforge_session_hint" in cookies
    for name in ("mapforge_session", "mapforge_session_hint"):
        meta = cookies[name]
        max_age = meta.get("max-age")
        assert max_age == "0", f"{name} should have max-age=0 on logout, got {meta}"


@pytest.mark.asyncio
async def test_missing_auth_returns_401(client):
    """/auth/me without cookie or Authorization must 401, not 500."""
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401
