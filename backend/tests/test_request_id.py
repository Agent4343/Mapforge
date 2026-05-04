"""Tests for the request-id contextvar and middleware."""

import pytest

from app.logging_config import get_request_id, reset_request_id, set_request_id


def test_contextvar_set_get_reset():
    assert get_request_id() is None
    token = set_request_id("abc-123")
    try:
        assert get_request_id() == "abc-123"
    finally:
        reset_request_id(token)
    assert get_request_id() is None


def test_contextvar_nested():
    outer = set_request_id("outer")
    try:
        assert get_request_id() == "outer"
        inner = set_request_id("inner")
        try:
            assert get_request_id() == "inner"
        finally:
            reset_request_id(inner)
        assert get_request_id() == "outer"
    finally:
        reset_request_id(outer)


@pytest.mark.asyncio
async def test_response_echoes_request_id_header(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    # Middleware always stamps an X-Request-ID on the response.
    rid = resp.headers.get("x-request-id")
    assert rid is not None
    assert len(rid) > 0


@pytest.mark.asyncio
async def test_inbound_request_id_is_preserved(client):
    resp = await client.get("/health", headers={"x-request-id": "req-from-edge-proxy"})
    assert resp.headers.get("x-request-id") == "req-from-edge-proxy"
