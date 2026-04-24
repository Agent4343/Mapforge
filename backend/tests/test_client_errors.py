"""Tests for the `/api/v1/client-errors` crash-report endpoint."""

import pytest


@pytest.mark.asyncio
async def test_accepts_valid_payload(client):
    resp = await client.post(
        "/api/v1/client-errors",
        json={
            "message": "Cannot read properties of undefined",
            "stack": "Error: …\n  at App (App.jsx:42)",
            "componentStack": "in App\nin ErrorBoundary",
            "url": "https://mapforge.app/",
            "userAgent": "Mozilla/5.0 (Test)",
        },
    )
    assert resp.status_code == 204
    assert resp.content == b""


@pytest.mark.asyncio
async def test_accepts_empty_body(client):
    """An empty POST shouldn't crash — the endpoint is best-effort."""
    resp = await client.post("/api/v1/client-errors")
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_accepts_invalid_json(client):
    """Garbage body must 204, not 400 — we never want the logger to surface
    errors back to the client."""
    resp = await client.post(
        "/api/v1/client-errors",
        content=b"not json at all",
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_rejects_oversized_body(client):
    """Cap on body size prevents a runaway component stack from
    DoS-ing the logger. Still returns 204 for the client."""
    huge = {"message": "x", "stack": "y" * (17 * 1024)}
    resp = await client.post("/api/v1/client-errors", json=huge)
    assert resp.status_code == 204
