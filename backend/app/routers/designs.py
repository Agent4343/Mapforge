"""Design ID system — save, retrieve, and manage map designs for Etsy fulfillment.

Core workflow:
1. Customer designs map on the app
2. Saves design → gets a Design ID (e.g. MS-A3F8K2)
3. Purchases on Etsy, enters Design ID in order notes
4. Admin searches by Design ID → exports print file → ships
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.logging_config import log
from app.models.db_models import SavedDesign, GeneratedFile, User
from app.models.schemas import (
    SaveDesignRequest, SaveDesignResponse,
    DesignDetailResponse, AdminUpdateDesignRequest,
)
from app.services.auth import get_current_user, get_optional_user

router = APIRouter(prefix="/api/v1/designs", tags=["designs"])
limiter = Limiter(key_func=get_remote_address)


@router.post("", response_model=SaveDesignResponse)
@limiter.limit("10/minute")
async def save_design(
    request: Request,
    req: SaveDesignRequest,
    db: AsyncSession = Depends(get_db),
):
    """Save a design and get a Design ID.

    No authentication required — anyone who designs a map can save it.
    The Design ID is what they provide on Etsy to complete their purchase.
    """
    design = SavedDesign(
        location_name=req.location_name,
        osm_id=req.osm_id,
        osm_type=req.osm_type,
        lat=req.lat,
        lon=req.lon,
        product_type=req.product_type,
        board_size=req.board_size,
        color_theme=req.color_theme,
        display_text=req.display_text,
        subtitle=req.subtitle,
        font_family=req.font_family,
        border_style=req.border_style,
        map_shape=req.map_shape,
        show_coordinates=req.show_coordinates,
        font_size_mm=req.font_size_mm,
        custom_bg=req.custom_bg,
        custom_land=req.custom_land,
        custom_water=req.custom_water,
        custom_road=req.custom_road,
        custom_text=req.custom_text,
        star_date=req.star_date,
        star_time=req.star_time,
        creator_email=req.creator_email,
        generated_file_id=req.generated_file_id,
    )

    db.add(design)
    try:
        await db.commit()
        await db.refresh(design)
    except Exception as e:
        await db.rollback()
        log.error(f"Failed to save design: {e}")
        raise HTTPException(status_code=500, detail="Failed to save design.")

    log.info(f"Design saved: {design.design_id} — {design.location_name}")

    return SaveDesignResponse(
        design_id=design.design_id,
        location_name=design.location_name,
        created_at=design.created_at.isoformat(),
    )


@router.get("/{design_id}", response_model=DesignDetailResponse)
async def get_design(design_id: str, db: AsyncSession = Depends(get_db)):
    """Retrieve a design by its Design ID.

    Public endpoint — anyone with the Design ID can view the design config.
    This lets the Etsy order form link back to the design.
    """
    design_id = design_id.upper().strip()
    result = await db.execute(
        select(SavedDesign).where(SavedDesign.design_id == design_id)
    )
    design = result.scalar_one_or_none()
    if not design:
        raise HTTPException(status_code=404, detail=f"Design '{design_id}' not found.")

    return DesignDetailResponse(
        design_id=design.design_id,
        location_name=design.location_name,
        product_type=design.product_type,
        board_size=design.board_size,
        color_theme=design.color_theme,
        display_text=design.display_text,
        subtitle=design.subtitle,
        font_family=design.font_family,
        border_style=design.border_style,
        map_shape=design.map_shape,
        show_coordinates=design.show_coordinates,
        font_size_mm=design.font_size_mm,
        lat=design.lat,
        lon=design.lon,
        osm_id=design.osm_id,
        osm_type=design.osm_type,
        custom_bg=design.custom_bg,
        custom_land=design.custom_land,
        custom_water=design.custom_water,
        custom_road=design.custom_road,
        custom_text=design.custom_text,
        star_date=design.star_date,
        star_time=design.star_time,
        generated_file_id=design.generated_file_id,
        order_status=design.order_status,
        etsy_order_id=design.etsy_order_id,
        tracking_number=design.tracking_number,
        created_at=design.created_at.isoformat(),
    )


@router.get("")
async def list_designs(
    status: str = "",
    search: str = "",
    page: int = 1,
    per_page: int = 20,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all designs (admin only). Supports filtering by status and search."""
    if user.tier != "admin":
        raise HTTPException(status_code=403, detail="Admin access required.")

    query = select(SavedDesign).order_by(SavedDesign.created_at.desc())

    if status:
        query = query.where(SavedDesign.order_status == status)
    if search:
        search_filter = f"%{search}%"
        query = query.where(
            SavedDesign.design_id.ilike(search_filter)
            | SavedDesign.location_name.ilike(search_filter)
            | SavedDesign.etsy_order_id.ilike(search_filter)
        )

    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    designs = result.scalars().all()

    return {
        "designs": [
            {
                "design_id": d.design_id,
                "location_name": d.location_name,
                "product_type": d.product_type,
                "board_size": d.board_size,
                "order_status": d.order_status,
                "etsy_order_id": d.etsy_order_id,
                "generated_file_id": d.generated_file_id,
                "created_at": d.created_at.isoformat(),
            }
            for d in designs
        ],
        "page": page,
        "per_page": per_page,
    }


@router.patch("/{design_id}")
async def update_design(
    design_id: str,
    req: AdminUpdateDesignRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a design's order status (admin only)."""
    if user.tier != "admin":
        raise HTTPException(status_code=403, detail="Admin access required.")

    design_id = design_id.upper().strip()
    result = await db.execute(
        select(SavedDesign).where(SavedDesign.design_id == design_id)
    )
    design = result.scalar_one_or_none()
    if not design:
        raise HTTPException(status_code=404, detail=f"Design '{design_id}' not found.")

    if req.order_status is not None:
        design.order_status = req.order_status
    if req.etsy_order_id is not None:
        design.etsy_order_id = req.etsy_order_id
    if req.tracking_number is not None:
        design.tracking_number = req.tracking_number
    if req.notes is not None:
        design.notes = req.notes

    await db.commit()
    log.info(f"Design {design_id} updated: status={design.order_status}")

    return {"status": "updated", "design_id": design_id}
