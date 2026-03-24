"""Customer order endpoints — pricing, checkout, fulfillment, and download.

Flow:
  1. Customer designs map (no auth required)
  2. GET  /api/v1/orders/price  → live price calculation
  3. POST /api/v1/orders/checkout → creates Stripe Checkout Session, returns URL
  4. Stripe webhook (checkout.session.completed) → triggers generation + email
  5. GET  /api/v1/orders/{token}/download → download files with token
"""

import json
import secrets
from datetime import datetime, timezone

import stripe
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session
from app.logging_config import log
from app.models.db_models import Order
from app.services.pricing import calculate_price

stripe.api_key = settings.STRIPE_SECRET_KEY

router = APIRouter(prefix="/api/v1/orders", tags=["orders"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class PriceRequest(BaseModel):
    product_type: str = "city"
    board_size: str = "print_16x20"
    include_streets: bool = False
    include_contours: bool = False
    num_markers: int = Field(0, ge=0, le=10)
    has_heart: bool = False
    print_dpi: int = 300
    border_style: str = "none"
    include_dxf: bool = False
    include_stl: bool = False


class CheckoutRequest(BaseModel):
    """Everything needed to create an order + redirect to Stripe."""
    email: str = Field(..., min_length=5, max_length=255)
    # Full design config (same as GenerateRequest fields)
    design_config: dict
    # Price inputs (for server-side re-calculation)
    product_type: str = "city"
    board_size: str = "print_16x20"
    include_streets: bool = False
    include_contours: bool = False
    num_markers: int = 0
    has_heart: bool = False
    print_dpi: int = 300
    border_style: str = "none"
    include_dxf: bool = False
    include_stl: bool = False
    # Redirect URLs
    success_url: str
    cancel_url: str


class OrderStatusResponse(BaseModel):
    order_id: str
    status: str
    location_name: str
    product_type: str
    price_display: str
    download_token: str | None = None
    file_id: str | None = None
    download_count: int = 0
    max_downloads: int = 5


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/price")
async def get_price(req: PriceRequest):
    """Calculate price for a design (no auth required)."""
    return calculate_price(
        product_type=req.product_type,
        board_size=req.board_size,
        include_streets=req.include_streets,
        include_contours=req.include_contours,
        num_markers=req.num_markers,
        has_heart=req.has_heart,
        print_dpi=req.print_dpi,
        border_style=req.border_style,
        include_dxf=req.include_dxf,
        include_stl=req.include_stl,
    )


@router.post("/checkout")
async def create_checkout(req: CheckoutRequest):
    """Create a Stripe Checkout Session and an Order record. Returns checkout URL."""
    # Server-side price calculation (never trust the client)
    pricing = calculate_price(
        product_type=req.product_type,
        board_size=req.board_size,
        include_streets=req.include_streets,
        include_contours=req.include_contours,
        num_markers=req.num_markers,
        has_heart=req.has_heart,
        print_dpi=req.print_dpi,
        border_style=req.border_style,
        include_dxf=req.include_dxf,
        include_stl=req.include_stl,
    )

    location_name = req.design_config.get("text") or req.design_config.get("label") or "Custom Map"

    # Create order in DB
    download_token = secrets.token_urlsafe(32)

    async with async_session() as db:
        order = Order(
            email=req.email,
            status="pending",
            design_config=json.dumps(req.design_config),
            product_type=req.product_type,
            board_size=req.board_size,
            location_name=location_name,
            price_cents=pricing["total_cents"],
            price_breakdown=json.dumps(pricing),
            download_token=download_token,
        )
        db.add(order)
        await db.commit()
        await db.refresh(order)
        order_id = order.id

    # Create Stripe Checkout Session
    if not settings.STRIPE_SECRET_KEY:
        # Dev mode — skip Stripe, mark as paid immediately
        log.warning("Stripe not configured — auto-completing order for dev mode")
        async with async_session() as db:
            result = await db.execute(select(Order).where(Order.id == order_id))
            order = result.scalar_one()
            order.status = "paid"
            order.paid_at = datetime.now(timezone.utc)
            await db.commit()
        return {
            "checkout_url": None,
            "order_id": order_id,
            "download_token": download_token,
            "dev_mode": True,
            "price": pricing,
        }

    try:
        session = stripe.checkout.Session.create(
            mode="payment",
            customer_email=req.email,
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "unit_amount": pricing["total_cents"],
                    "product_data": {
                        "name": f"Custom Map Print — {location_name}",
                        "description": f"{pricing['size_label']} {req.product_type.replace('_', ' ').title()} Map",
                    },
                },
                "quantity": 1,
            }],
            metadata={
                "order_id": order_id,
                "order_type": "map_design",
            },
            success_url=req.success_url + "?order_token=" + download_token,
            cancel_url=req.cancel_url,
        )
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=502, detail=f"Payment error: {str(e)}")

    # Save checkout session ID
    async with async_session() as db:
        result = await db.execute(select(Order).where(Order.id == order_id))
        order = result.scalar_one()
        order.stripe_checkout_session_id = session.id
        await db.commit()

    return {
        "checkout_url": session.url,
        "order_id": order_id,
        "price": pricing,
    }


@router.get("/status/{download_token}")
async def get_order_status(download_token: str):
    """Check order status by download token (no auth required)."""
    async with async_session() as db:
        result = await db.execute(
            select(Order).where(Order.download_token == download_token)
        )
        order = result.scalar_one_or_none()

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    breakdown = json.loads(order.price_breakdown) if order.price_breakdown else {}

    return OrderStatusResponse(
        order_id=order.id,
        status=order.status,
        location_name=order.location_name,
        product_type=order.product_type,
        price_display=breakdown.get("total_display", f"${order.price_cents / 100:.2f}"),
        download_token=order.download_token if order.status == "completed" else None,
        file_id=order.file_id if order.status == "completed" else None,
        download_count=order.download_count,
        max_downloads=order.max_downloads,
    )


@router.get("/download/{download_token}")
async def download_order_files(download_token: str, format: str = Query("png")):
    """Download generated files using the order's download token."""
    from fastapi.responses import StreamingResponse
    from app.services.file_storage import get_file

    async with async_session() as db:
        result = await db.execute(
            select(Order).where(Order.download_token == download_token)
        )
        order = result.scalar_one_or_none()

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.status != "completed":
        raise HTTPException(status_code=400, detail=f"Order is not ready yet (status: {order.status})")

    if not order.file_id:
        raise HTTPException(status_code=400, detail="Files have not been generated yet")

    if order.download_count >= order.max_downloads:
        raise HTTPException(status_code=403, detail="Download limit reached. Contact support for help.")

    # Get the generated file record
    from app.models.db_models import GeneratedFile
    async with async_session() as db:
        file_result = await db.execute(
            select(GeneratedFile).where(GeneratedFile.id == order.file_id)
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
        raise HTTPException(status_code=400, detail=f"Format '{format}' not available for this order")

    file_data = await get_file(key)
    if not file_data:
        raise HTTPException(status_code=404, detail="File data not found in storage")

    # Increment download count
    async with async_session() as db:
        result = await db.execute(select(Order).where(Order.id == order.id))
        o = result.scalar_one()
        o.download_count += 1
        await db.commit()

    safe_name = order.location_name.replace(" ", "_").lower()[:50]
    return StreamingResponse(
        iter([file_data]),
        media_type=content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}_{format}.{filename_ext}"'
        },
    )


@router.get("/link")
async def generate_etsy_link(
    product_type: str = "lake",
    board_size: str = "print_16x20",
    color_theme: str = "classic",
):
    """Generate a link-back URL for Etsy listings.

    Put this URL in your Etsy listing description:
      "Design your custom map at: {url}"

    When customers click it, they land on your app with pre-filled settings.
    """
    frontend_url = settings.FRONTEND_URL or "http://localhost:5173"
    params = f"?ref=etsy&product_type={product_type}&board_size={board_size}&color_theme={color_theme}"
    return {
        "url": frontend_url + params,
        "markdown": f"[Design Your Custom Map]({frontend_url}{params})",
        "html": f'<a href="{frontend_url}{params}">Design Your Custom Map</a>',
    }
