"""Etsy integration router — OAuth 2.0 connection and listing publishing."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.logging_config import log
from app.models.db_models import GeneratedFile, User
from app.services.app_settings import get_etsy_credentials
from app.services.auth import get_current_user
from app.services.etsy_client import (
    create_draft_listing,
    exchange_code,
    generate_auth_url,
    get_shop,
    get_valid_token,
    is_configured,
    update_listing_type,
    upload_listing_file,
    upload_listing_image,
)
from app.services.file_storage import retrieve_file

router = APIRouter(prefix="/api/v1/etsy", tags=["etsy"])


# --- Schemas ---

class EtsyPublishRequest(BaseModel):
    file_id: str
    title: str = Field(..., max_length=140)
    description: str = Field(..., max_length=5000)
    price: float = Field(..., ge=0.20, le=99.99)
    tags: list[str] = Field(default_factory=list, max_length=13)


class EtsyPublishResponse(BaseModel):
    listing_id: int
    listing_url: str
    status: str = "draft"


class EtsyStatusResponse(BaseModel):
    connected: bool
    shop_name: str | None = None
    shop_id: str | None = None


# --- Endpoints ---

@router.get("/status", response_model=EtsyStatusResponse)
async def etsy_status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Check if the user has connected their Etsy shop."""
    creds = await get_etsy_credentials(db)
    if not is_configured(creds):
        return EtsyStatusResponse(connected=False)

    return EtsyStatusResponse(
        connected=bool(user.etsy_access_token),
        shop_name=user.etsy_shop_name,
        shop_id=user.etsy_shop_id,
    )


@router.get("/connect")
async def etsy_connect(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Start the Etsy OAuth 2.0 flow. Redirects user to Etsy for authorization."""
    creds = await get_etsy_credentials(db)
    if not is_configured(creds):
        raise HTTPException(status_code=503, detail="Etsy integration is not configured. Set ETSY_API_KEY and ETSY_API_SECRET.")

    auth_url = generate_auth_url(user.id, creds=creds)
    return {"auth_url": auth_url}


@router.get("/callback")
async def etsy_callback(
    code: str,
    state: str,
    db: AsyncSession = Depends(get_db),
):
    """Handle the OAuth callback from Etsy. Exchanges code for tokens."""
    user_id = state

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=400, detail="Invalid state — user not found.")

    creds = await get_etsy_credentials(db)

    try:
        tokens = await exchange_code(user_id, code, creds=creds)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Save tokens
    user.etsy_access_token = tokens["access_token"]
    user.etsy_refresh_token = tokens.get("refresh_token")
    user.etsy_token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=tokens.get("expires_in", 3600))

    # Fetch shop info
    try:
        shop = await get_shop(tokens["access_token"], creds=creds)
        user.etsy_shop_id = str(shop["shop_id"])
        user.etsy_shop_name = shop.get("shop_name", "")
    except Exception as e:
        log.warning("Failed to fetch Etsy shop info: %s", e)

    await db.commit()

    # Redirect back to the app frontend
    frontend_url = settings.FRONTEND_URL or "http://localhost:3000"
    return RedirectResponse(url=f"{frontend_url}?etsy_connected=1")


@router.post("/disconnect")
async def etsy_disconnect(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Disconnect Etsy shop from the user's account."""
    user.etsy_access_token = None
    user.etsy_refresh_token = None
    user.etsy_token_expires_at = None
    user.etsy_shop_id = None
    user.etsy_shop_name = None
    await db.commit()
    return {"status": "disconnected"}


@router.post("/publish", response_model=EtsyPublishResponse)
async def etsy_publish(
    req: EtsyPublishRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Publish a generated map as a draft listing on Etsy.

    Creates the listing, uploads the listing image, and attaches
    the SVG as a digital download file. The listing is created as a
    draft — you can review and activate it on Etsy.
    """
    creds = await get_etsy_credentials(db)

    if not is_configured(creds):
        raise HTTPException(status_code=503, detail="Etsy integration is not configured.")

    if not user.etsy_access_token:
        raise HTTPException(status_code=400, detail="Etsy not connected. Connect your shop first.")

    if not user.etsy_shop_id:
        raise HTTPException(status_code=400, detail="No Etsy shop found. Reconnect your Etsy account.")

    # Get the generated file
    result = await db.execute(
        select(GeneratedFile).where(GeneratedFile.id == req.file_id)
    )
    file_record = result.scalar_one_or_none()
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found.")

    if file_record.owner_id and file_record.owner_id != user.id:
        raise HTTPException(status_code=403, detail="You don't own this file.")

    # Get a valid access token (refreshes if expired)
    try:
        access_token = await get_valid_token(user, creds=creds)
        await db.commit()  # persist any refreshed tokens
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))

    shop_id = user.etsy_shop_id

    # 1. Create draft listing
    try:
        listing = await create_draft_listing(
            access_token=access_token,
            shop_id=shop_id,
            title=req.title,
            description=req.description,
            price=req.price,
            tags=req.tags,
            creds=creds,
        )
    except ValueError as e:
        raise HTTPException(status_code=502, detail=f"Etsy API error: {e}")

    listing_id = listing["listing_id"]

    # 2. Upload Etsy listing image
    etsy_key = file_record.svg_storage_key.replace("svg/", "etsy/").replace(".svg", "_etsy.png")
    etsy_img = await retrieve_file(etsy_key)
    if etsy_img:
        try:
            await upload_listing_image(
                access_token=access_token,
                shop_id=shop_id,
                listing_id=listing_id,
                image_bytes=etsy_img,
                filename=f"{file_record.location_name.replace(' ', '_')}_listing.png",
                creds=creds,
            )
        except ValueError as e:
            log.warning("Etsy image upload failed (listing still created): %s", e)

    # 3. Upload thumbnail as second image
    if file_record.thumbnail_key:
        thumb_bytes = await retrieve_file(file_record.thumbnail_key)
        if thumb_bytes:
            try:
                await upload_listing_image(
                    access_token=access_token,
                    shop_id=shop_id,
                    listing_id=listing_id,
                    image_bytes=thumb_bytes,
                    filename=f"{file_record.location_name.replace(' ', '_')}_mockup.png",
                    rank=2,
                    creds=creds,
                )
            except ValueError as e:
                log.warning("Etsy thumbnail upload failed: %s", e)

    # 4. Upload SVG as the digital download file, then set type to "download".
    #    Per Etsy docs: create draft → upload file → PATCH type=download.
    svg_bytes = await retrieve_file(file_record.svg_storage_key)
    if svg_bytes:
        try:
            await upload_listing_file(
                access_token=access_token,
                shop_id=shop_id,
                listing_id=listing_id,
                file_bytes=svg_bytes,
                filename=f"{file_record.location_name.replace(' ', '_')}_mapforge.svg",
                creds=creds,
            )
            # Now mark the listing as a digital download
            await update_listing_type(
                access_token=access_token,
                shop_id=shop_id,
                listing_id=listing_id,
                listing_type="download",
                creds=creds,
            )
        except ValueError as e:
            log.warning("Etsy digital file upload/type-update failed: %s", e)

    listing_url = f"https://www.etsy.com/listing/{listing_id}"
    log.info("Published Etsy draft listing %d for user %s: %s", listing_id, user.id, file_record.location_name)

    return EtsyPublishResponse(
        listing_id=listing_id,
        listing_url=listing_url,
        status="draft",
    )
