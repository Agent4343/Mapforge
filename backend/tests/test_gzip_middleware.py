"""Test that the GZip middleware actually compresses large responses."""

import pytest
from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from httpx import ASGITransport, AsyncClient


def _app_with_gzip():
    """Fresh FastAPI app with the same GZip config the real app uses.
    Isolated so we don't depend on the main app's routers."""
    app = FastAPI()
    app.add_middleware(GZipMiddleware, minimum_size=1024)

    @app.get("/large")
    async def large():
        # 20 KB of repeated text compresses to a tiny fraction.
        return {"payload": "mapforge" * 2500}

    @app.get("/small")
    async def small():
        return {"ok": True}

    return app


@pytest.mark.asyncio
async def test_large_response_is_compressed():
    app = _app_with_gzip()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/large", headers={"accept-encoding": "gzip"})
    assert resp.status_code == 200
    # httpx transparently decompresses, so we can't directly read bytes —
    # but Content-Encoding: gzip in the response headers proves the
    # middleware compressed on the way out.
    assert resp.headers.get("content-encoding") == "gzip"


@pytest.mark.asyncio
async def test_small_response_is_not_compressed():
    """Below the 1024-byte threshold gzip overhead isn't worth it."""
    app = _app_with_gzip()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/small", headers={"accept-encoding": "gzip"})
    assert resp.status_code == 200
    assert resp.headers.get("content-encoding") is None


@pytest.mark.asyncio
async def test_client_without_gzip_support_gets_plain():
    """Respect the client's accept-encoding."""
    app = _app_with_gzip()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/large", headers={"accept-encoding": "identity"})
    assert resp.status_code == 200
    assert resp.headers.get("content-encoding") is None
