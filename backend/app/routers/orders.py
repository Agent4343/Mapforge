"""Customer design credit endpoints — redeem Etsy purchase, design, generate, download.

Flow:
  1. Customer buys a map product on your Etsy shop
  2. Etsy webhook (order.paid) auto-creates a DesignCredit with a unique token
  3. Customer receives a link (in Etsy digital download) to your app with the token
  4. GET  /api/v1/orders/redeem/{token}  → validates token, returns credit info
  5. POST /api/v1/orders/generate/{token} → customer submits design, files are generated
  6. GET  /api/v1/orders/download/{token} → download generated files
  7. GET  /api/v1/orders/status/{token}   → check generation progress

No second payment — customer already paid on Etsy.
"""

import json
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.config import settings
from app.database import async_session
from app.logging_config import log
from app.models.db_models import DesignCredit, GeneratedFile, User
from app.services.auth import get_current_user

router = APIRouter(prefix="/api/v1/orders", tags=["orders"])


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _is_credit_expired(credit: DesignCredit) -> bool:
    expires_at = getattr(credit, "expires_at", None)
    return bool(expires_at and expires_at <= _utcnow())


def _resolved_expiry_for_new_credit() -> datetime:
    return _utcnow() + timedelta(days=30)


def _resolved_download_limit() -> int:
    """Always enforce one-time customer downloads for Etsy credits."""
    return 1


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class RedeemResponse(BaseModel):
    token: str
    status: str
    product_type: str | None = None
    product_tier: str = "standard"
    etsy_listing_title: str | None = None
    location_name: str | None = None
    file_id: str | None = None
    download_count: int = 0
    max_downloads: int = 1


class GenerateDesignRequest(BaseModel):
    """Design configuration submitted by the customer after designing their map."""
    design_config: dict  # Full GenerateRequest fields as dict


class CreditStatusResponse(BaseModel):
    token: str
    status: str
    location_name: str | None = None
    product_type: str | None = None
    file_id: str | None = None
    download_count: int = 0
    max_downloads: int = 1


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/redeem/{token}")
async def redeem_credit(token: str):
    """Validate a design credit token and return its details.

    This is the first thing the customer's browser calls when they click the
    link from Etsy. If the token is valid and unused, the customer can proceed
    to design their map.
    """
    async with async_session() as db:
        result = await db.execute(
            select(DesignCredit).where(DesignCredit.redeem_token == token)
        )
        credit = result.scalar_one_or_none()

    if not credit:
        raise HTTPException(status_code=404, detail="Invalid or expired design credit. Please check your Etsy purchase confirmation for the correct link.")

    if credit.status == "expired" or _is_credit_expired(credit):
        raise HTTPException(status_code=410, detail="This design credit has expired. Please contact the seller.")

    return RedeemResponse(
        token=credit.redeem_token,
        status=credit.status,
        product_type=credit.product_type,
        product_tier=credit.product_tier,
        etsy_listing_title=credit.etsy_listing_title,
        location_name=credit.location_name,
        file_id=credit.file_id if credit.status == "completed" else None,
        download_count=credit.download_count,
        max_downloads=credit.max_downloads,
    )


@router.post("/generate/{token}")
async def generate_design(token: str, req: GenerateDesignRequest):
    """Submit a design configuration and generate the map files.

    The customer designs their map in the frontend, then hits this endpoint.
    The design is saved and files are generated immediately.
    """
    import asyncio

    async with async_session() as db:
        result = await db.execute(
            select(DesignCredit).where(DesignCredit.redeem_token == token)
        )
        credit = result.scalar_one_or_none()

    if not credit:
        raise HTTPException(status_code=404, detail="Invalid design credit")

    if credit.status == "completed":
        if credit.download_count >= _resolved_download_limit():
            raise HTTPException(status_code=410, detail="This design has already been downloaded.")
        # Already generated — just return the existing result
        return CreditStatusResponse(
            token=credit.redeem_token,
            status="completed",
            location_name=credit.location_name,
            product_type=credit.product_type,
            file_id=credit.file_id,
            download_count=credit.download_count,
            max_downloads=credit.max_downloads,
        )

    if credit.status == "generating":
        raise HTTPException(status_code=409, detail="Your map is already being generated. Please wait.")

    if credit.status not in ("unused", "designing"):
        raise HTTPException(status_code=400, detail=f"Credit cannot be used (status: {credit.status})")

    location_name = req.design_config.get("text") or req.design_config.get("label") or "Custom Map"

    # Save design config and start generating
    async with async_session() as db:
        result = await db.execute(
            select(DesignCredit).where(DesignCredit.redeem_token == token)
        )
        credit = result.scalar_one()
        credit.design_config = json.dumps(req.design_config)
        credit.location_name = location_name
        credit.status = "generating"
        credit.redeemed_at = datetime.now(timezone.utc)
        await db.commit()
        credit_id = credit.id

    # Run generation (may take 30-60s)
    asyncio.create_task(_fulfill_credit(credit_id))

    return CreditStatusResponse(
        token=token,
        status="generating",
        location_name=location_name,
        product_type=credit.product_type,
    )


@router.get("/status/{token}")
async def get_credit_status(token: str):
    """Check the generation status of a design credit."""
    async with async_session() as db:
        result = await db.execute(
            select(DesignCredit).where(DesignCredit.redeem_token == token)
        )
        credit = result.scalar_one_or_none()

    if not credit:
        raise HTTPException(status_code=404, detail="Credit not found")

    if _is_credit_expired(credit):
        raise HTTPException(status_code=410, detail="Credit has expired")

    return CreditStatusResponse(
        token=credit.redeem_token,
        status=credit.status,
        location_name=credit.location_name,
        product_type=credit.product_type,
        file_id=credit.file_id if credit.status == "completed" else None,
        download_count=credit.download_count,
        max_downloads=credit.max_downloads,
    )


@router.get("/download/{token}")
async def download_files(token: str, format: str = Query("png")):
    """Download generated files using the design credit token."""
    from fastapi.responses import StreamingResponse
    from app.services.file_storage import retrieve_file

    async with async_session() as db:
        result = await db.execute(
            select(DesignCredit).where(DesignCredit.redeem_token == token)
        )
        credit = result.scalar_one_or_none()

    if not credit:
        raise HTTPException(status_code=404, detail="Invalid credit token")

    if credit.status == "downloaded":
        raise HTTPException(status_code=410, detail="This design has already been downloaded.")

    if credit.status != "completed":
        raise HTTPException(status_code=400, detail=f"Files are not ready yet (status: {credit.status})")

    if not credit.file_id:
        raise HTTPException(status_code=400, detail="Files have not been generated yet")

    if credit.status == "downloaded":
        raise HTTPException(status_code=410, detail="This design has already been downloaded.")

    if _is_credit_expired(credit):
        raise HTTPException(status_code=410, detail="Credit has expired")

    if credit.download_count >= _resolved_download_limit():
        raise HTTPException(status_code=410, detail="This design has already been downloaded.")

    # Get the generated file record
    async with async_session() as db:
        file_result = await db.execute(
            select(GeneratedFile).where(GeneratedFile.id == credit.file_id)
        )
        gen_file = file_result.scalar_one_or_none()

    if not gen_file:
        raise HTTPException(status_code=404, detail="Generated file not found")

    # Determine which file to serve
    key = None
    content_type = "application/octet-stream"
    filename_ext = format

    if format == "png" and gen_file.print_png_key:
        key = gen_file.print_png_key
        content_type = "image/png"
    elif format == "svg":
        key = gen_file.svg_storage_key
        content_type = "image/svg+xml"
    elif format == "dxf" and gen_file.dxf_storage_key:
        key = gen_file.dxf_storage_key
    elif format == "thumbnail" and gen_file.thumbnail_key:
        key = gen_file.thumbnail_key
        content_type = "image/png"
        filename_ext = "png"
    else:
        raise HTTPException(status_code=400, detail=f"Format '{format}' not available")

    file_data = await retrieve_file(key)
    if not file_data:
        raise HTTPException(status_code=404, detail="File data not found in storage")

    # One-time download flow:
    # 1) mark credit as consumed
    # 2) remove generated assets and unlink DB references so file cannot be fetched again
    async with async_session() as db:
        from app.services.file_storage import delete_file

        # Lock the credit row to avoid concurrent double-downloads.
        credit_result = await db.execute(
            select(DesignCredit).where(DesignCredit.id == credit.id).with_for_update()
        )
        c = credit_result.scalar_one()
        if c.download_count >= _resolved_download_limit():
            raise HTTPException(status_code=410, detail="This design has already been downloaded.")
        if c.status in {"downloaded", "expired"}:
            raise HTTPException(status_code=410, detail="This design has already been downloaded.")

        file_result = await db.execute(
            select(GeneratedFile).where(GeneratedFile.id == c.file_id).with_for_update()
        )
        file_row = file_result.scalar_one_or_none()
        keys_to_delete = []
        if file_row:
            keys_to_delete.extend(
                [
                    file_row.svg_storage_key,
                    file_row.dxf_storage_key,
                    file_row.thumbnail_key,
                    file_row.print_png_key,
                    file_row.print_pdf_key,
                ]
            )

        # Mark the credit consumed before external deletes.
        result = await db.execute(select(DesignCredit).where(DesignCredit.id == credit.id))
        c = result.scalar_one()
        c.download_count += 1
        c.status = "downloaded"
        c.expires_at = _utcnow()
        c.downloaded_at = _utcnow()
        c.file_id = None
        await db.commit()

        # Best-effort storage cleanup after commit.
        for key_name in keys_to_delete:
            if not key_name:
                continue
            try:
                await delete_file(key_name)
            except Exception as e:
                log.warning(f"Failed deleting storage key {key_name}: {e}")

        # Remove DB references so legacy/admin paths cannot re-download.
        if file_row:
            async with async_session() as cleanup_db:
                cleanup_result = await cleanup_db.execute(
                    select(GeneratedFile).where(GeneratedFile.id == file_row.id)
                )
                cleanup_file = cleanup_result.scalar_one_or_none()
                if cleanup_file:
                    cleanup_file.svg_storage_key = f"deleted/{cleanup_file.id}.svg"
                    cleanup_file.dxf_storage_key = None
                    cleanup_file.thumbnail_key = None
                    cleanup_file.print_png_key = None
                    cleanup_file.print_pdf_key = None
                    await cleanup_db.commit()

    safe_name = (credit.location_name or "mapforge").replace(" ", "_").lower()[:50]
    return StreamingResponse(
        iter([file_data]),
        media_type=content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}.{filename_ext}"'
        },
    )


# ---------------------------------------------------------------------------
# Etsy link generation (for listing descriptions)
# ---------------------------------------------------------------------------

@router.get("/etsy-link")
async def generate_etsy_link(
    product_type: str = "lake",
    product_tier: str = "standard",
):
    """Generate a link template for your Etsy listing description.

    You don't put the token in the Etsy listing — the token is auto-generated
    when a customer buys. Instead, the Etsy digital download PDF will contain
    the unique design link.

    This endpoint gives you the marketing link for the listing description.
    """
    frontend_url = settings.FRONTEND_URL or "http://localhost:5173"
    link = f"{frontend_url}?ref=etsy&product_type={product_type}&tier={product_tier}"
    return {
        "listing_description_link": link,
        "note": "This is the preview link for your listing description. The actual design link with the unique token is sent to the customer after purchase via the Etsy digital download.",
    }


# ---------------------------------------------------------------------------
# Admin: manually create design credits (for testing or non-Etsy sales)
# ---------------------------------------------------------------------------

@router.post("/credits/create")
async def create_credit_manually(
    product_type: str = "lake",
    product_tier: str = "standard",
    etsy_buyer_email: str | None = None,
    max_downloads: int = 1,
    user: User = Depends(get_current_user),
):
    """Manually create a design credit (admin/testing use).

    Returns the unique design link that you can share with a customer.
    """
    if user.tier != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    token = secrets.token_urlsafe(32)
    frontend_url = settings.FRONTEND_URL or "http://localhost:5173"

    async with async_session() as db:
        credit = DesignCredit(
            product_type=product_type,
            product_tier=product_tier,
            etsy_buyer_email=etsy_buyer_email,
            seller_id=user.id,
            redeem_token=token,
            max_downloads=_resolved_download_limit(),
            expires_at=_resolved_expiry_for_new_credit(),
        )
        db.add(credit)
        await db.commit()

    design_url = f"{frontend_url}?credit={token}"

    return {
        "credit_id": credit.id,
        "token": token,
        "design_url": design_url,
        "product_type": product_type,
        "product_tier": product_tier,
    }


# ---------------------------------------------------------------------------
# Background: generate files for a credit
# ---------------------------------------------------------------------------

async def _fulfill_credit(credit_id: str):
    """Generate map files for a redeemed design credit."""
    from app.routers.generate import _do_generate
    from app.models.schemas import GenerateRequest

    async with async_session() as db:
        result = await db.execute(
            select(DesignCredit).where(DesignCredit.id == credit_id)
        )
        credit = result.scalar_one_or_none()
        if not credit or credit.status != "generating":
            return

    try:
        design = json.loads(credit.design_config)
        req = GenerateRequest(**design)

        async with async_session() as db:
            # Credit fulfillment must persist generated assets, so run as seller/admin.
            credit_row = await db.get(DesignCredit, credit_id)
            seller_user = None
            if credit_row and credit_row.seller_id:
                seller_user = await db.get(User, credit_row.seller_id)
            gen_response = await _do_generate(req, user=seller_user, db=db)

        async with async_session() as db:
            result = await db.execute(
                select(DesignCredit).where(DesignCredit.id == credit_id)
            )
            credit = result.scalar_one_or_none()
            if not credit:
                log.error(f"Design credit {credit_id} not found after generation")
                return
            credit.file_id = gen_response.file_id
            credit.status = "completed"
            credit.completed_at = datetime.now(timezone.utc)
            await db.commit()

        log.info(f"Design credit {credit_id} fulfilled — file_id={gen_response.file_id}")

    except Exception as e:
        log.error(f"Design credit {credit_id} generation failed: {e}")
        async with async_session() as db:
            result = await db.execute(
                select(DesignCredit).where(DesignCredit.id == credit_id)
            )
            credit = result.scalar_one_or_none()
            if not credit:
                log.error(f"Design credit {credit_id} not found during error recovery")
                return
            credit.status = "unused"  # Reset so customer can try again
            await db.commit()
