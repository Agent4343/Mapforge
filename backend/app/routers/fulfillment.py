"""Fulfillment worker for EtsyPurchase orders.

This module provides two ways to run fulfilment:

1. **Background polling loop** (started automatically on app startup via
   ``start_fulfillment_loop``).  It wakes up every
   ``FULFILLMENT_POLL_SECONDS`` seconds and processes any ``pending``
   EtsyPurchase rows.

2. **HTTP trigger endpoint** ``POST /api/v1/fulfillment/process`` that an
   external scheduler (e.g. Railway Cron, GitHub Actions cron, cURL from a
   systemd timer) can call to process pending purchases immediately.

Multi-instance safety
---------------------
Processing is guarded by an atomic status transition:
  ``UPDATE etsy_purchases SET status='generating' WHERE status='pending' AND id=?``
Only the instance that successfully updates the row continues with generation;
other instances skip the row.

Fulfillment steps
-----------------
1. Load design config from the associated BuildDraft.
2. Generate the final map output using the existing generation pipeline,
   persisting the output even without a user account.
3. Upload the generated PNG to Etsy as the digital file attachment for the
   listing (so the buyer can download directly on Etsy).
4. Mark the EtsyPurchase as ``delivered``.
"""

import asyncio
import json
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session
from app.logging_config import log
from app.models.db_models import BuildDraft, EtsyPurchase, GeneratedFile, PublishedListing, User

router = APIRouter(prefix="/api/v1/fulfillment", tags=["fulfillment"])

FULFILLMENT_POLL_SECONDS = 30  # interval between background polling runs


# ---------------------------------------------------------------------------
# HTTP trigger endpoint
# ---------------------------------------------------------------------------

@router.post("/process")
async def process_pending():
    """Process all pending EtsyPurchase fulfilments.

    This endpoint is designed to be called by an external scheduler.  It
    returns a summary of how many purchases were processed.

    It is safe to call concurrently from multiple instances because each
    purchase is claimed atomically by a status transition.
    """
    processed, failed = await _run_fulfillment_pass()
    return {"processed": processed, "failed": failed}


# ---------------------------------------------------------------------------
# Background polling loop
# ---------------------------------------------------------------------------

async def start_fulfillment_loop():
    """Start the background polling loop.  Called from the app lifespan."""
    log.info("Fulfillment loop started (poll every %ds)", FULFILLMENT_POLL_SECONDS)
    while True:
        try:
            processed, failed = await _run_fulfillment_pass()
            if processed or failed:
                log.info("Fulfillment pass: processed=%d failed=%d", processed, failed)
        except Exception as exc:
            log.error("Fulfillment loop error: %s", exc)
        await asyncio.sleep(FULFILLMENT_POLL_SECONDS)


# ---------------------------------------------------------------------------
# Core fulfilment logic
# ---------------------------------------------------------------------------

async def _run_fulfillment_pass() -> tuple[int, int]:
    """Process all pending EtsyPurchase rows.  Returns (processed, failed)."""
    processed = 0
    failed = 0

    async with async_session() as db:
        result = await db.execute(
            select(EtsyPurchase).where(EtsyPurchase.status == "pending")
        )
        pending = result.scalars().all()

    for purchase in pending:
        ok = await _claim_and_fulfill(purchase.id)
        if ok is True:
            processed += 1
        elif ok is False:
            failed += 1
        # None means another instance claimed it first — skip silently

    return processed, failed


async def _claim_and_fulfill(purchase_id: str) -> bool | None:
    """Atomically claim a purchase and fulfil it.

    Returns:
        True   – successfully delivered
        False  – generation/upload failed (marked as ``failed`` in DB)
        None   – purchase was already claimed by another instance
    """
    # Atomic claim: only proceed if we are the one to flip status to 'generating'
    async with async_session() as db:
        result = await db.execute(
            update(EtsyPurchase)
            .where(EtsyPurchase.id == purchase_id, EtsyPurchase.status == "pending")
            .values(status="generating")
            .returning(EtsyPurchase.id)
        )
        claimed_id = result.scalar_one_or_none()
        await db.commit()

    if claimed_id is None:
        return None  # Another instance claimed it

    log.info("Fulfilling EtsyPurchase %s", purchase_id)

    try:
        file_id = await _do_fulfill(purchase_id)
        async with async_session() as db:
            await db.execute(
                update(EtsyPurchase)
                .where(EtsyPurchase.id == purchase_id)
                .values(
                    status="delivered",
                    file_id=file_id,
                    completed_at=datetime.now(timezone.utc),
                    error_message=None,
                )
            )
            await db.commit()
        log.info("EtsyPurchase %s delivered (file_id=%s)", purchase_id, file_id)
        return True

    except Exception as exc:
        log.error("EtsyPurchase %s fulfilment failed: %s", purchase_id, exc)
        async with async_session() as db:
            await db.execute(
                update(EtsyPurchase)
                .where(EtsyPurchase.id == purchase_id)
                .values(status="failed", error_message=str(exc))
            )
            await db.commit()
        return False


async def _do_fulfill(purchase_id: str) -> str:
    """Perform the actual generation and Etsy upload for one purchase.

    Returns the ``file_id`` of the generated file.
    """
    from app.routers.generate import _do_generate
    from app.models.schemas import GenerateRequest

    # Load purchase + linked draft
    async with async_session() as db:
        purchase_result = await db.execute(
            select(EtsyPurchase).where(EtsyPurchase.id == purchase_id)
        )
        purchase = purchase_result.scalar_one_or_none()
        if not purchase:
            raise RuntimeError(f"EtsyPurchase {purchase_id} not found")

        listing_result = await db.execute(
            select(PublishedListing).where(PublishedListing.id == purchase.published_listing_id)
        )
        pub_listing = listing_result.scalar_one_or_none()
        if not pub_listing:
            raise RuntimeError(f"PublishedListing {purchase.published_listing_id} not found")

        draft_result = await db.execute(
            select(BuildDraft).where(BuildDraft.id == pub_listing.build_draft_id)
        )
        draft = draft_result.scalar_one_or_none()
        if not draft or not draft.design_config:
            raise RuntimeError(f"BuildDraft for listing {pub_listing.id} missing or has no design_config")

        design = json.loads(draft.design_config)

    # Generate — persist even though there is no authenticated user
    req = GenerateRequest(**design)
    async with async_session() as db:
        gen_response = await _do_generate(req, user=None, db=db, persist_anonymous=True)

    if not gen_response.file_id:
        raise RuntimeError("Generation did not produce a file_id")

    file_id: str = gen_response.file_id

    # Upload the generated print PNG to Etsy as the digital download file
    await _upload_to_etsy(pub_listing.etsy_listing_id, file_id)

    return file_id


async def _upload_to_etsy(etsy_listing_id: str, file_id: str) -> None:
    """Attach the generated file to the Etsy listing as a digital download."""
    from app.services.etsy_client import get_valid_token, upload_listing_file
    from app.services.app_settings import get_etsy_credentials
    from app.services.file_storage import retrieve_file

    async with async_session() as db:
        file_result = await db.execute(
            select(GeneratedFile).where(GeneratedFile.id == file_id)
        )
        gen_file = file_result.scalar_one_or_none()
        if not gen_file:
            raise RuntimeError(f"GeneratedFile {file_id} not found")

        seller_result = await db.execute(
            select(User).where(User.etsy_access_token.isnot(None), User.etsy_shop_id.isnot(None))
        )
        seller = seller_result.scalars().first()
        if not seller:
            raise RuntimeError("No connected Etsy shop found for fulfilment upload")

        creds = await get_etsy_credentials(db)
        access_token = await get_valid_token(seller, creds=creds)
        await db.commit()

    # Prefer print PNG, fall back to SVG
    key = gen_file.print_png_key or gen_file.svg_storage_key
    if not key:
        raise RuntimeError(f"GeneratedFile {file_id} has no storable output key")

    file_bytes = await retrieve_file(key)
    if not file_bytes:
        raise RuntimeError(f"Storage key {key} returned no data")

    location_safe = (gen_file.location_name or "mapforge").replace(" ", "_")[:50]
    ext = "png" if gen_file.print_png_key else "svg"
    filename = f"{location_safe}_print.{ext}"

    await upload_listing_file(
        access_token=access_token,
        shop_id=seller.etsy_shop_id,
        listing_id=int(etsy_listing_id),
        file_bytes=file_bytes,
        filename=filename,
        creds=creds,
    )
    log.info("Uploaded %s to Etsy listing %s", filename, etsy_listing_id)
