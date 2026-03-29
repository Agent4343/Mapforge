"""Template library router — save, list, filter, re-export."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.db_models import GeneratedFile, MarketplaceListing, User, DesignCredit
from app.models.schemas import LibraryFileResponse, LibraryResponse
from app.services.auth import get_current_user

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/library", tags=["library"])


@router.get("", response_model=LibraryResponse)
async def list_library(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    product_type: str | None = None,
    province: str | None = None,
    search: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List user's generated file library with filtering."""
    query = select(GeneratedFile).where(GeneratedFile.owner_id == user.id)

    if product_type:
        query = query.where(GeneratedFile.product_type == product_type)
    if province:
        query = query.where(GeneratedFile.province == province)
    if search:
        query = query.where(GeneratedFile.location_name.ilike(f"%{search}%"))

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Paginate
    query = query.order_by(GeneratedFile.created_at.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)

    result = await db.execute(query)
    files = result.scalars().all()

    # Check which files are listed on marketplace
    file_ids = [f.id for f in files]
    listings_result = await db.execute(
        select(MarketplaceListing.file_id).where(
            MarketplaceListing.file_id.in_(file_ids),
            MarketplaceListing.is_active == True,
        )
    )
    listed_ids = {row[0] for row in listings_result.all()}

    items = [
        LibraryFileResponse(
            id=f.id,
            location_name=f.location_name,
            display_text=f.display_text,
            product_type=f.product_type,
            board_size=f.board_size,
            board_width_mm=f.board_width_mm,
            board_height_mm=f.board_height_mm,
            style=f.style,
            node_count=f.node_count,
            path_count=f.path_count,
            province=f.province,
            lat=f.lat,
            lon=f.lon,
            has_dxf=f.dxf_storage_key is not None,
            is_listed=f.id in listed_ids,
            created_at=f.created_at.isoformat(),
        )
        for f in files
    ]

    return LibraryResponse(files=items, total=total, page=page, per_page=per_page)


@router.delete("/all", status_code=200)
async def delete_all_files(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete all files from the user's library (skips marketplace-listed files)."""
    from app.services.file_storage import delete_file as delete_stored

    # Get all user's files
    result = await db.execute(
        select(GeneratedFile).where(GeneratedFile.owner_id == user.id)
    )
    all_files = result.scalars().all()

    if not all_files:
        return {"deleted": 0, "skipped": 0}

    # Find which ones are listed on marketplace
    file_ids = [f.id for f in all_files]
    listings_result = await db.execute(
        select(MarketplaceListing.file_id).where(
            MarketplaceListing.file_id.in_(file_ids),
            MarketplaceListing.is_active == True,
        )
    )
    listed_ids = {row[0] for row in listings_result.all()}

    # Also find files referenced by design credits (can't delete those, just nullify the FK)
    credit_refs = await db.execute(
        select(DesignCredit.file_id).where(
            DesignCredit.file_id.in_(file_ids),
            DesignCredit.file_id.isnot(None),
        )
    )
    credit_file_ids = {row[0] for row in credit_refs.all()}

    # Also find files with ANY marketplace listing (active or inactive)
    all_listings = await db.execute(
        select(MarketplaceListing.file_id).where(
            MarketplaceListing.file_id.in_(file_ids),
        )
    )
    any_listed_ids = {row[0] for row in all_listings.all()}

    deleted = 0
    skipped = 0
    for f in all_files:
        if f.id in listed_ids:
            skipped += 1
            continue
        # Nullify design credit references before deleting
        if f.id in credit_file_ids:
            await db.execute(
                select(DesignCredit).where(DesignCredit.file_id == f.id)
            )
            from sqlalchemy import update
            await db.execute(
                update(DesignCredit).where(DesignCredit.file_id == f.id).values(file_id=None)
            )
        # Remove inactive marketplace listings that reference this file
        if f.id in any_listed_ids and f.id not in listed_ids:
            await db.execute(
                delete(MarketplaceListing).where(MarketplaceListing.file_id == f.id)
            )
        # Clean up all storage keys, tolerating errors on individual files
        for key in (f.svg_storage_key, f.dxf_storage_key, f.thumbnail_key, f.print_png_key):
            if key:
                try:
                    await delete_stored(key)
                except Exception as exc:
                    log.warning("Failed to delete storage key %s: %s", key, exc)
        await db.delete(f)
        deleted += 1

    await db.commit()
    log.info("User %s deleted all library files: %d deleted, %d skipped", user.id, deleted, skipped)
    return {"deleted": deleted, "skipped": skipped}


@router.delete("/{file_id}", status_code=204)
async def delete_file(
    file_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a file from the library."""
    result = await db.execute(
        select(GeneratedFile).where(
            GeneratedFile.id == file_id,
            GeneratedFile.owner_id == user.id,
        )
    )
    file_record = result.scalar_one_or_none()
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")

    # Check if listed on marketplace
    listing_result = await db.execute(
        select(MarketplaceListing).where(MarketplaceListing.file_id == file_id)
    )
    if listing_result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Cannot delete a file that is listed on the marketplace. Remove the listing first.")

    # Nullify any design credit references to this file
    from sqlalchemy import update
    await db.execute(
        update(DesignCredit).where(DesignCredit.file_id == file_id).values(file_id=None)
    )

    from app.services.file_storage import delete_file as delete_stored
    for key in (file_record.svg_storage_key, file_record.dxf_storage_key,
                file_record.thumbnail_key, file_record.print_png_key):
        if key:
            try:
                await delete_stored(key)
            except Exception as exc:
                log.warning("Failed to delete storage key %s: %s", key, exc)

    await db.delete(file_record)
    await db.commit()
