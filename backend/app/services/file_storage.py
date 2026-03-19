"""File storage service — local filesystem or S3-compatible."""

import os
import re
from pathlib import Path

import httpx

from app.config import settings
from app.logging_config import log

# Allowed characters in storage keys — prevents path traversal
_SAFE_KEY_RE = re.compile(r"^[a-zA-Z0-9_/.\-]+$")

# Maximum file size: 50 MB
MAX_FILE_SIZE = 50 * 1024 * 1024


def _validate_key(key: str) -> str:
    """Validate storage key to prevent path traversal attacks."""
    if not key or ".." in key or key.startswith("/") or not _SAFE_KEY_RE.match(key):
        raise ValueError(f"Invalid storage key: {key!r}")
    return key


async def store_file(key: str, content: bytes, content_type: str = "image/svg+xml") -> str:
    """Store a file and return its storage key."""
    _validate_key(key)
    if len(content) > MAX_FILE_SIZE:
        raise ValueError(f"File too large ({len(content)} bytes, max {MAX_FILE_SIZE})")
    if settings.STORAGE_BACKEND == "s3":
        return await _store_s3(key, content, content_type)
    return _store_local(key, content)


async def retrieve_file(key: str) -> bytes | None:
    """Retrieve file content by key."""
    _validate_key(key)
    if settings.STORAGE_BACKEND == "s3":
        return await _retrieve_s3(key)
    return _retrieve_local(key)


async def delete_file(key: str) -> bool:
    """Delete a file by key."""
    _validate_key(key)
    if settings.STORAGE_BACKEND == "s3":
        return await _delete_s3(key)
    return _delete_local(key)


# --- Local filesystem ---

def _store_local(key: str, content: bytes) -> str:
    base = Path(settings.STORAGE_LOCAL_PATH)
    filepath = base / key
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_bytes(content)
    log.info(f"Stored file locally: {key} ({len(content)} bytes)")
    return key


def _retrieve_local(key: str) -> bytes | None:
    filepath = Path(settings.STORAGE_LOCAL_PATH) / key
    if not filepath.exists():
        return None
    return filepath.read_bytes()


def _delete_local(key: str) -> bool:
    filepath = Path(settings.STORAGE_LOCAL_PATH) / key
    if filepath.exists():
        filepath.unlink()
        return True
    return False


# --- S3-compatible (Supabase Storage, AWS S3, etc.) ---

def _s3_headers(content_type: str | None = None) -> dict:
    """Build S3 auth headers. Supports Supabase Storage (Bearer) and generic S3."""
    headers = {}
    if content_type:
        headers["Content-Type"] = content_type
    # Use apikey header for Supabase Storage, Bearer for other S3-compatible stores
    if settings.S3_ACCESS_KEY:
        headers["Authorization"] = f"Bearer {settings.S3_ACCESS_KEY}"
    if settings.S3_SECRET_KEY:
        headers["apikey"] = settings.S3_SECRET_KEY
    return headers


async def _store_s3(key: str, content: bytes, content_type: str) -> str:
    """Upload to S3-compatible storage."""
    url = f"{settings.S3_ENDPOINT}/{settings.S3_BUCKET}/{key}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.put(url, content=content, headers=_s3_headers(content_type))
        resp.raise_for_status()
    log.info(f"Stored file to S3: {key} ({len(content)} bytes)")
    return key


async def _retrieve_s3(key: str) -> bytes | None:
    url = f"{settings.S3_ENDPOINT}/{settings.S3_BUCKET}/{key}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url, headers=_s3_headers())
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.content


async def _delete_s3(key: str) -> bool:
    url = f"{settings.S3_ENDPOINT}/{settings.S3_BUCKET}/{key}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.delete(url, headers=_s3_headers())
        return resp.status_code in (200, 204, 404)
