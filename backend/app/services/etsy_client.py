"""Etsy API v3 client — OAuth 2.0 PKCE flow and listing management.

Etsy's API v3 uses OAuth 2.0 with PKCE (Proof Key for Code Exchange).
Docs: https://developers.etsy.com/documentation/

This service handles:
  - OAuth authorization URL generation (with PKCE)
  - Token exchange and refresh (JSON body per Quick Start tutorial)
  - Creating draft listings for digital products
  - Uploading listing images and digital download files
  - Correct digital listing workflow: create draft → upload file → PATCH type=download
  - Rate limit handling (429 with retry-after + exponential backoff)

Credentials are loaded from the database (app_settings table) first,
falling back to environment variables.
"""

import asyncio
import base64
import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

ETSY_AUTH_URL = "https://www.etsy.com/oauth/connect"
ETSY_TOKEN_URL = "https://api.etsy.com/v3/public/oauth/token"
ETSY_API_BASE = "https://api.etsy.com/v3"

# Max retries for 429 rate limit responses
MAX_RETRIES = 3

# PKCE verifiers stored temporarily (keyed by user ID)
_pkce_store: dict[str, str] = {}


# --- Credential helpers ---
# Functions accept an optional `creds` dict with keys: api_key, api_secret, redirect_uri.
# When creds is None, falls back to env var settings (for backward compatibility).

def _get_api_key(creds: Optional[dict] = None) -> str:
    if creds and creds.get("api_key"):
        return creds["api_key"]
    return settings.ETSY_API_KEY


def _get_api_secret(creds: Optional[dict] = None) -> str:
    if creds and creds.get("api_secret"):
        return creds["api_secret"]
    return settings.ETSY_API_SECRET


def _get_redirect_uri(creds: Optional[dict] = None) -> str:
    if creds and creds.get("redirect_uri"):
        return creds["redirect_uri"]
    return settings.ETSY_REDIRECT_URI


def is_configured(creds: Optional[dict] = None) -> bool:
    """Check if Etsy API credentials are set (DB or env vars)."""
    return bool(_get_api_key(creds) and _get_api_secret(creds))


def _api_key_header(creds: Optional[dict] = None) -> str:
    """Build the x-api-key header value: keystring:shared_secret.

    As of February 2026, Etsy requires both the keystring and shared secret
    in the x-api-key header, separated by a colon.
    """
    return f"{_get_api_key(creds)}:{_get_api_secret(creds)}"


def extract_etsy_user_id(access_token: str) -> str:
    """Extract the Etsy numeric user ID from the access token.

    Etsy access tokens are formatted as {user_id}.{token}.
    """
    parts = access_token.split(".", 1)
    if len(parts) != 2 or not parts[0].isdigit():
        raise ValueError("Invalid Etsy access token format — expected {user_id}.{token}")
    return parts[0]


async def _request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    **kwargs,
) -> httpx.Response:
    """Execute an HTTP request with retry on 429 (rate limited).

    Uses the retry-after header when available, falls back to exponential backoff.
    """
    for attempt in range(MAX_RETRIES + 1):
        resp = await client.request(method, url, **kwargs)
        if resp.status_code != 429:
            return resp

        if attempt == MAX_RETRIES:
            logger.error("Etsy rate limit exceeded after %d retries: %s", MAX_RETRIES, url)
            return resp

        retry_after = resp.headers.get("retry-after")
        if retry_after and retry_after.isdigit():
            wait = int(retry_after)
        else:
            wait = 2 ** (attempt + 1)  # 2s, 4s, 8s

        logger.warning("Etsy 429 rate limited on %s, retrying in %ds (attempt %d/%d)", url, wait, attempt + 1, MAX_RETRIES)
        await asyncio.sleep(wait)

    return resp  # unreachable but satisfies type checker


def generate_auth_url(user_id: str, creds: Optional[dict] = None) -> str:
    """Generate the Etsy OAuth 2.0 authorization URL with PKCE.

    Returns the URL the user should be redirected to for granting access.
    """
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")
    _pkce_store[user_id] = code_verifier

    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")

    params = {
        "response_type": "code",
        "client_id": _get_api_key(creds),
        "redirect_uri": _get_redirect_uri(creds),
        "scope": "listings_w listings_r shops_r listings_d",
        "state": user_id,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    from urllib.parse import urlencode
    return f"{ETSY_AUTH_URL}?{urlencode(params)}"


async def exchange_code(user_id: str, code: str, creds: Optional[dict] = None) -> dict:
    """Exchange the authorization code for access + refresh tokens.

    Per the Etsy Quick Start tutorial, the token endpoint accepts
    Content-Type: application/json with a JSON body.

    Returns dict with: access_token, refresh_token, expires_in, token_type.
    The access_token is formatted as {user_id}.{token}.
    """
    code_verifier = _pkce_store.pop(user_id, None)
    if not code_verifier:
        raise ValueError("PKCE verifier not found — authorization flow expired or already used.")

    payload = {
        "grant_type": "authorization_code",
        "client_id": _get_api_key(creds),
        "redirect_uri": _get_redirect_uri(creds),
        "code": code,
        "code_verifier": code_verifier,
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            ETSY_TOKEN_URL,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=15.0,
        )

    if resp.status_code != 200:
        logger.error("Etsy token exchange failed: %d %s", resp.status_code, resp.text[:300])
        raise ValueError(f"Etsy token exchange failed: {resp.status_code}")

    return resp.json()


async def refresh_access_token(refresh_token: str, creds: Optional[dict] = None) -> dict:
    """Refresh an expired access token using the refresh token.

    Returns dict with new: access_token, refresh_token, expires_in.
    """
    payload = {
        "grant_type": "refresh_token",
        "client_id": _get_api_key(creds),
        "refresh_token": refresh_token,
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            ETSY_TOKEN_URL,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=15.0,
        )

    if resp.status_code != 200:
        logger.error("Etsy token refresh failed: %d %s", resp.status_code, resp.text[:300])
        raise ValueError("Etsy token refresh failed — user may need to reconnect.")

    return resp.json()


def _is_token_expired(expires_at: Optional[datetime]) -> bool:
    """Check if the token is expired or about to expire (5 min buffer)."""
    if not expires_at:
        return True
    return datetime.now(timezone.utc) >= expires_at - timedelta(minutes=5)


async def get_valid_token(user, creds: Optional[dict] = None) -> str:
    """Get a valid access token, refreshing if needed. Updates user in place."""
    if not user.etsy_access_token:
        raise ValueError("Etsy not connected. Please connect your Etsy shop first.")

    if not _is_token_expired(user.etsy_token_expires_at):
        return user.etsy_access_token

    if not user.etsy_refresh_token:
        raise ValueError("Etsy refresh token missing. Please reconnect your Etsy shop.")

    tokens = await refresh_access_token(user.etsy_refresh_token, creds=creds)
    user.etsy_access_token = tokens["access_token"]
    user.etsy_refresh_token = tokens.get("refresh_token", user.etsy_refresh_token)
    user.etsy_token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=tokens["expires_in"])
    return tokens["access_token"]


def _auth_headers(access_token: str, creds: Optional[dict] = None) -> dict:
    """Build standard auth headers for Etsy API requests."""
    return {
        "x-api-key": _api_key_header(creds),
        "Authorization": f"Bearer {access_token}",
    }


async def get_shop(access_token: str, creds: Optional[dict] = None) -> dict:
    """Get the user's Etsy shop info using their user ID from the access token."""
    user_id = extract_etsy_user_id(access_token)
    headers = _auth_headers(access_token, creds)

    async with httpx.AsyncClient() as client:
        resp = await _request_with_retry(
            client, "GET",
            f"{ETSY_API_BASE}/application/users/{user_id}/shops",
            headers=headers,
            timeout=15.0,
        )

    if resp.status_code != 200:
        logger.error("Etsy get_shop failed: %d %s", resp.status_code, resp.text[:500])
        raise ValueError(f"Failed to fetch Etsy shop: {resp.status_code} — {resp.text[:200]}")

    data = resp.json()
    logger.info("Etsy get_shop response keys: %s", list(data.keys()) if isinstance(data, dict) else type(data))

    # The response may be a single shop object or have results array
    if isinstance(data, dict) and "shop_id" in data:
        return data
    # Etsy v3 wraps results in a "results" array for getShopByOwnerUserId
    results = data.get("results", [])
    if not results:
        # Some Etsy accounts don't have a shop yet
        logger.warning("Etsy get_shop: no results in response: %s", str(data)[:300])
        raise ValueError("No Etsy shop found for this account. Make sure you have an active Etsy shop.")

    return results[0]


async def create_draft_listing(
    access_token: str,
    shop_id: str,
    title: str,
    description: str,
    price: float,
    tags: list[str],
    quantity: int = 999,
    creds: Optional[dict] = None,
) -> dict:
    """Create a draft listing on Etsy.

    Per the Listings Tutorial, createDraftListing uses
    Content-Type: application/x-www-form-urlencoded.

    For digital products, the listing is created as a draft first.
    The type is set to "download" separately via update_listing_type()
    AFTER uploading the digital file with upload_listing_file().
    """
    headers = _auth_headers(access_token, creds)

    tag_list = [t.strip()[:20] for t in tags[:13] if t.strip()]

    payload = {
        "title": title[:140],
        "description": description,
        "price": str(price),
        "quantity": str(quantity),
        "who_made": "i_did",
        "when_made": "made_to_order",
        "taxonomy_id": "69150433",
        "should_auto_renew": "true",
    }
    if tag_list:
        payload["tags"] = ",".join(tag_list)

    async with httpx.AsyncClient() as client:
        resp = await _request_with_retry(
            client, "POST",
            f"{ETSY_API_BASE}/application/shops/{shop_id}/listings",
            headers=headers,
            data=payload,
            timeout=20.0,
        )

    if resp.status_code not in (200, 201):
        logger.error("Etsy listing creation failed: %d %s", resp.status_code, resp.text[:500])
        raise ValueError(f"Failed to create Etsy listing: {resp.text[:200]}")

    return resp.json()


async def update_listing_type(
    access_token: str,
    shop_id: str,
    listing_id: int,
    listing_type: str = "download",
    creds: Optional[dict] = None,
) -> dict:
    """Update a listing's type via PATCH (e.g., set to 'download' for digital).

    Per the Listings Tutorial, after uploading a digital file you must
    PATCH the listing to set type='download'.
    """
    headers = _auth_headers(access_token, creds)

    payload = {"type": listing_type}

    async with httpx.AsyncClient() as client:
        resp = await _request_with_retry(
            client, "PATCH",
            f"{ETSY_API_BASE}/application/shops/{shop_id}/listings/{listing_id}",
            headers=headers,
            data=payload,
            timeout=15.0,
        )

    if resp.status_code not in (200, 201):
        logger.error("Etsy listing update failed: %d %s", resp.status_code, resp.text[:300])
        raise ValueError(f"Failed to update Etsy listing type: {resp.text[:200]}")

    return resp.json()


async def upload_listing_image(
    access_token: str,
    shop_id: str,
    listing_id: int,
    image_bytes: bytes,
    filename: str = "listing.png",
    rank: int = 1,
    creds: Optional[dict] = None,
) -> dict:
    """Upload an image to an Etsy listing (multipart/form-data)."""
    headers = _auth_headers(access_token, creds)

    files = {
        "image": (filename, image_bytes, "image/png"),
    }
    data = {"rank": str(rank)}

    async with httpx.AsyncClient() as client:
        resp = await _request_with_retry(
            client, "POST",
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
    creds: Optional[dict] = None,
) -> dict:
    """Upload a digital file to an Etsy listing (the file buyers download)."""
    headers = _auth_headers(access_token, creds)

    files = {
        "file": (filename, file_bytes, "application/octet-stream"),
    }
    data = {"rank": str(rank)}

    async with httpx.AsyncClient() as client:
        resp = await _request_with_retry(
            client, "POST",
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


async def send_buyer_message(
    access_token: str,
    shop_id: str,
    receipt_id: str,
    message: str,
    creds: Optional[dict] = None,
) -> bool:
    """Send a message to a buyer via Etsy Conversations API.

    Uses the shop receipt to identify the buyer and send them a message
    with their custom design link.

    Returns True if the message was sent successfully.
    """
    headers = _auth_headers(access_token, creds)

    # Etsy API: POST /v3/application/shops/{shop_id}/receipts/{receipt_id}/send-message
    # This sends a message to the buyer associated with the receipt
    async with httpx.AsyncClient() as client:
        # First try the receipt-based messaging endpoint
        resp = await _request_with_retry(
            client, "POST",
            f"{ETSY_API_BASE}/application/shops/{shop_id}/receipts/{receipt_id}/messages",
            headers=headers,
            json={"message": message},
            timeout=15.0,
        )

    if resp.status_code in (200, 201):
        logger.info(f"Sent Etsy message to buyer for receipt {receipt_id}")
        return True

    # Log but don't raise — messaging is best-effort
    logger.warning(
        f"Etsy buyer message failed ({resp.status_code}): {resp.text[:200]}. "
        f"Design link must be delivered manually."
    )
    return False


def generate_instruction_file(shop_name: str = "MapForgeDesign", frontend_url: str = "") -> bytes:
    """Generate a generic instruction text file for Etsy digital download.

    This file is uploaded to each listing. It tells buyers what to expect
    and how to access their custom design tool.
    """
    url = frontend_url or "https://mapforge-production.up.railway.app"

    content = f"""
===========================================
   Welcome to {shop_name}!
   Your Custom Map Print
===========================================

Thank you for your purchase!

HOW TO GET YOUR CUSTOM MAP:
---------------------------

1. Check your Etsy Messages - we'll send you a unique
   design link within a few minutes of your purchase.

2. Click the link to open our design tool.

3. Choose any location in the world - your hometown,
   where you got married, your favorite vacation spot.

4. Customize the colors, style, text, and size.

5. Download your print-ready files instantly!

WHAT YOU'LL RECEIVE:
- High-resolution PNG (up to 600 DPI)
- SVG vector source file
- Product mockup image
- Up to 5 downloads

NEED HELP?
----------
If you haven't received your design link within
30 minutes, please send us a message on Etsy
and we'll get it to you right away.

Visit us: {url}

Happy designing!
- The {shop_name} Team
"""
    return content.strip().encode("utf-8")
