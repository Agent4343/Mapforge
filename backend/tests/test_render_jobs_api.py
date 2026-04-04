"""Tests for professional render job API."""

import pytest


@pytest.mark.asyncio
async def test_render_jobs_requires_auth(client):
    resp = await client.post("/api/v1/render/jobs", json={
        "file_id": "does-not-matter",
        "formats": ["png"],
        "dpi": 600,
        "engine_profile": "professional_print",
    })
    assert resp.status_code == 401

