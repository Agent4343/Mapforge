"""Etsy API v3 client — OAuth 2.0 PKCE flow and listing management.

Etsy's API v3 uses OAuth 2.0 with PKCE (Proof Key for Code Exchange).
Docs: https://developers.etsy.com/documentation/essentials/authentication

This service handles:
  - OAuth authorization URL generation (with PKCE)
  - Token exchange and refresh
  - Creating draft listings with images
  - Uploading digital files to listings
"""

import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

ETSY_AUTH_URL = "https://www.etsy.com/oauth/connect"
ETSY_TOKEN_URL = "https://api.etsy.com/v3/public/oauth/token"
ETSY_API_BASE = "https://api.etsy.com/v3"

# PKCE verifiers stored temporarily (keyed by user ID)
_pkce_store: dict[str, str] = {}


def is_configured() -> bool:
    """Check if Etsy API credentials are set."""
    return bool(settings.ETSY_API_KEY and settings.ETSY_API_SECRET)


def _api_key_header() -> str:
    """Build the x-api-key header value: keystring:shared_secret."""
    return f"{settings.ETSY_API_KEY}:{settings.ETSY_API_SECRET}"


def generate_auth_url(user_id: str) -> str:
    """Generate the Etsy OAuth 2.0 authorization URL with PKCE.

    Returns the URL the user should be redirected to for granting access.
    """
    # Generate PKCE code verifier and challenge
    code_verifier = secrets.token_urlsafe(64)[:128]
    _pkce_store[user_id] = code_verifier

    code_challenge = (
        hashlib.sha256(code_verifier.encode("ascii"))
        .digest()
    )
    import base64
    code_challenge_b64 = base64.urlsafe_b64encode(code_challenge).rstrip(b"=").decode("ascii")

    params = {
        "response_type": "code",
        "client_id": settings.ETSY_API_KEY,
        "redirect_uri": settings.ETSY_REDIRECT_URI,
        "scope": "listings_w listings_r shops_r images_w listings_d",
        "state": user_id,
        "code_challenge": code_challenge_b64,
        "code_challenge_method": "S256",
    }
    qs = "&".join(f"{k}={httpx.URL('', params={k: v}).params[k]}" for k, v in params.items())
    return f"{ETSY_AUTH_URL}?{qs}"


async def exchange_code(user_id: str, code: str) -> dict:
    """Exchange the authorization code for access + refresh tokens.

    Returns dict with: access_token, refresh_token, expires_in, token_type.
    """
    code_verifier = _pkce_store.pop(user_id, None)
    if not code_verifier:
        raise ValueError("PKCE verifier not found — authorization flow expired or already used.")

    payload = {
        "grant_type": "authorization_code",
        "client_id": settings.ETSY_API_KEY,
        "redirect_uri": settings.ETSY_REDIRECT_URI,
        "code": code,
        "code_verifier": code_verifier,
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(ETSY_TOKEN_URL, data=payload, timeout=15.0)

    if resp.status_code != 200:
        logger.error("Etsy token exchange failed: %d %s", resp.status_code, resp.text[:300])
        raise ValueError(f"Etsy token exchange failed: {resp.status_code}")

    return resp.json()


async def refresh_access_token(refresh_token: str) -> dict:
    """Refresh an expired access token using the refresh token.

    Returns dict with new: access_token, refresh_token, expires_in.
    """
    payload = {
        "grant_type": "refresh_token",
        "client_id": settings.ETSY_API_KEY,
        "refresh_token": refresh_token,
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(ETSY_TOKEN_URL, data=payload, timeout=15.0)

    if resp.status_code != 200:
        logger.error("Etsy token refresh failed: %d %s", resp.status_code, resp.text[:300])
        raise ValueError("Etsy token refresh failed — user may need to reconnect.")

    return resp.json()


def _is_token_expired(expires_at: Optional[datetime]) -> bool:
    """Check if the token is expired or about to expire (5 min buffer)."""
    if not expires_at:
        return True
    return datetime.now(timezone.utc) >= expires_at - timedelta(minutes=5)


async def get_valid_token(user) -> str:
    """Get a valid access token, refreshing if needed. Updates user in place."""
    if not user.etsy_access_token:
        raise ValueError("Etsy not connected. Please connect your Etsy shop first.")

    if not _is_token_expired(user.etsy_token_expires_at):
        return user.etsy_access_token

    if not user.etsy_refresh_token:
        raise ValueError("Etsy refresh token missing. Please reconnect your Etsy shop.")

    tokens = await refresh_access_token(user.etsy_refresh_token)
    user.etsy_access_token = tokens["access_token"]
    user.etsy_refresh_token = tokens.get("refresh_token", user.etsy_refresh_token)
    user.etsy_token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=tokens["expires_in"])
    return tokens["access_token"]


async def get_shop(access_token: str) -> dict:
    """Get the user's Etsy shop info. Returns first shop found."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "x-api-key": _api_key_header(),
    }

    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{ETSY_API_BASE}/application/shops", headers=headers, timeout=15.0)

    if resp.status_code != 200:
        raise ValueError(f"Failed to fetch Etsy shop: {resp.status_code}")

    data = resp.json()
    results = data.get("results", [])
    if not results:
        raise ValueError("No Etsy shop found for this account.")

    return results[0]


async def create_draft_listing(
    access_token: str,
    shop_id: str,
    title: str,
    description: str,
    price: float,
    tags: list[str],
    quantity: int = 999,
) -> dict:
    """Create a draft listing on Etsy.

    Etsy digital listings are created as drafts — you review and activate on Etsy.
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "x-api-key": _api_key_header(),
    }

    # Etsy v3 expects application/x-www-form-urlencoded for listing creation.
    # Tags are sent as comma-separated values; price as a float string.
    tag_list = [t[:20] for t in tags[:13]]  # Etsy: max 13 tags, 20 chars each

    payload = {
        "title": title[:140],
        "description": description,
        "price": str(price),
        "quantity": str(quantity),
        "tags": ",".join(tag_list),
        "who_made": "i_did",
        "when_made": "made_to_order",
        "taxonomy_id": "69150433",  # Craft Supplies & Tools > Digital Downloads
        "type": "download",
        "is_digital": "true",
        "should_auto_renew": "true",
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{ETSY_API_BASE}/application/shops/{shop_id}/listings",
            headers=headers,
            data=payload,
            timeout=20.0,
        )

    if resp.status_code not in (200, 201):
        logger.error("Etsy listing creation failed: %d %s", resp.status_code, resp.text[:500])
        raise ValueError(f"Failed to create Etsy listing: {resp.text[:200]}")

    return resp.json()


async def upload_listing_image(
    access_token: str,
    shop_id: str,
    listing_id: int,
    image_bytes: bytes,
    filename: str = "listing.png",
    rank: int = 1,
) -> dict:
    """Upload an image to an Etsy listing."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "x-api-key": _api_key_header(),
    }

    files = {
        "image": (filename, image_bytes, "image/png"),
    }
    data = {"rank": str(rank)}

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{ETSY_API_BASE}/application/shops/{shop_id}/listings/{listing_id}/images",
            headers=headers,
            files=files,
            data=data,
            timeout=30.0,
        )

    if resp.status_code not in (200, 201):
        logger.error("Etsy image upload failed: %d %s", resp.status_code, resp.text[:300])
        raise ValueError(f"Failed to upload image to Etsy: {resp.status_code}")

    return resp.json()


async def upload_listing_file(
    access_token: str,
    shop_id: str,
    listing_id: int,
    file_bytes: bytes,
    filename: str,
    rank: int = 1,
) -> dict:
    """Upload a digital file to an Etsy listing (the file buyers download)."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "x-api-key": _api_key_header(),
    }

    files = {
        "file": (filename, file_bytes, "application/octet-stream"),
    }
    data = {"rank": str(rank)}

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{ETSY_API_BASE}/application/shops/{shop_id}/listings/{listing_id}/files",
            headers=headers,
            files=files,
            data=data,
            timeout=60.0,
        )

    if resp.status_code not in (200, 201):
        logger.error("Etsy file upload failed: %d %s", resp.status_code, resp.text[:300])
        raise ValueError(f"Failed to upload file to Etsy: {resp.status_code}")

    return resp.json()
