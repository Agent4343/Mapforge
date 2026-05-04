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
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.config import settings
from app.database import async_session
from app.logging_config import log
from app.models.db_models import DesignCredit, GeneratedFile

router = APIRouter(prefix="/api/v1/orders", tags=["orders"])


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
    max_downloads: int = 5


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
    max_downloads: int = 5


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

    if credit.status == "expired":
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

    if credit.status != "completed":
        raise HTTPException(status_code=400, detail=f"Files are not ready yet (status: {credit.status})")

    if not credit.file_id:
        raise HTTPException(status_code=400, detail="Files have not been generated yet")

    if credit.download_count >= credit.max_downloads:
        raise HTTPException(status_code=403, detail="Download limit reached. Contact the seller for help.")

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

    # Increment download count
    async with async_session() as db:
        result = await db.execute(select(DesignCredit).where(DesignCredit.id == credit.id))
        c = result.scalar_one()
        c.download_count += 1
        await db.commit()

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
    max_downloads: int = 5,
):
    """Manually create a design credit (admin/testing use).

    Returns the unique design link that you can share with a customer.
    """
    token = secrets.token_urlsafe(32)
    frontend_url = settings.FRONTEND_URL or "http://localhost:5173"

    async with async_session() as db:
        credit = DesignCredit(
            product_type=product_type,
            product_tier=product_tier,
            etsy_buyer_email=etsy_buyer_email,
            redeem_token=token,
            max_downloads=max_downloads,
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
    """Generate map files for a redeemed design credit.

    Runs as a background coroutine.  Uses ``persist_anonymous=True`` so
    that a ``GeneratedFile`` DB record is always written even though no
    authenticated user is involved in the credit flow.
    """
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
            gen_response = await _do_generate(req, user=None, db=db, persist_anonymous=True)

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
