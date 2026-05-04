"""Etsy integration router — OAuth 2.0 connection and listing publishing."""

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session, get_db
from app.logging_config import log
from app.models.db_models import BuildDraft, GeneratedFile, PublishedListing, User
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


class EtsyPushRequest(BaseModel):
    """Push an anonymous design draft to Etsy as a new private/unlisted listing.

    The caller must supply either an existing *draft_token* (obtained from
    ``POST /api/v1/drafts``) **or** a full *design_config* dict.  When only
    a *design_config* is provided a BuildDraft record is created implicitly.
    """
    draft_token: str | None = Field(None, description="Token from a prior POST /api/v1/drafts call")
    design_config: dict | None = Field(None, description="Full GenerateRequest fields as a dict (alternative to draft_token)")
    title: str = Field(..., max_length=140)
    description: str = Field(..., max_length=5000)
    price: float = Field(..., ge=0.20, le=99.99)
    tags: list[str] = Field(default_factory=list, max_length=13)


class EtsyPushResponse(BaseModel):
    draft_token: str
    listing_id: int
    listing_url: str
    status: str = "draft"


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
    request: Request,
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
    error_description: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Handle the OAuth callback from Etsy. Exchanges code for tokens."""
    frontend_url = settings.FRONTEND_URL or "https://mapforge-production.up.railway.app"

    # Handle OAuth errors or denied authorization
    if error or not code or not state:
        log.warning("Etsy OAuth callback error: %s — %s", error, error_description)
        return RedirectResponse(url=f"{frontend_url}?etsy_error={error or 'missing_code'}")

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

    # 4. Upload instruction file as the digital download, then set type to "download".
    #    The instruction file tells buyers to check Etsy messages for their
    #    unique design link (sent automatically by the webhook handler).
    #    Per Etsy docs: create draft -> upload file -> PATCH type=download.
    try:
        from app.services.etsy_client import generate_instruction_file
        instruction_bytes = generate_instruction_file(
            shop_name=user.etsy_shop_name or "MapForgeDesign",
            frontend_url=settings.FRONTEND_URL or "https://mapforge-production.up.railway.app",
        )
        await upload_listing_file(
            access_token=access_token,
            shop_id=shop_id,
            listing_id=listing_id,
            file_bytes=instruction_bytes,
            filename="MapForge_Your_Custom_Map_Instructions.txt",
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


# ---------------------------------------------------------------------------
# Anonymous Push-to-Etsy (no auth required)
# ---------------------------------------------------------------------------

def _find_connected_seller(db_result):
    """Return the first User that has an Etsy shop connected."""
    return db_result.scalar_one_or_none()


@router.post("/push", response_model=EtsyPushResponse)
async def etsy_push(
    req: EtsyPushRequest,
    db: AsyncSession = Depends(get_db),
):
    """Push an anonymous map design to Etsy as a new private/unlisted listing.

    No user account is required.  The shop owner's Etsy credentials (stored
    via the admin Etsy-connect flow) are used to create the listing on
    behalf of the shop.

    Typical client flow
    -------------------
    1. User designs map in the browser.
    2. Client calls ``POST /api/v1/drafts`` to save the design and get a
       *draft_token* (or passes *design_config* directly here).
    3. Client calls this endpoint with *draft_token* (or *design_config*),
       *title*, *description*, *price*, and optional *tags*.
    4. Endpoint creates (or reuses) the BuildDraft, creates the Etsy listing,
       stores a PublishedListing mapping, and returns the Etsy listing URL.
    5. User opens the URL on Etsy and completes the purchase.
    6. Etsy fires an ``order.paid`` webhook which creates an EtsyPurchase and
       triggers the fulfillment worker.

    **Etsy listing visibility note**: Etsy does not support fully unlisted /
    private-URL-only listings via the API.  The listing is created as a
    *draft* (invisible to the public until manually activated).  Sellers
    should share the direct listing URL with the buyer instead of activating
    the listing in their public shop.  See README for details.
    """
    creds = await get_etsy_credentials(db)
    if not is_configured(creds):
        raise HTTPException(status_code=503, detail="Etsy integration is not configured. Set ETSY_API_KEY and ETSY_API_SECRET.")

    # Find the shop owner — the one connected Etsy account for this instance
    seller_result = await db.execute(
        select(User).where(User.etsy_access_token.isnot(None), User.etsy_shop_id.isnot(None))
    )
    seller = seller_result.scalars().first()
    if not seller:
        raise HTTPException(status_code=503, detail="No Etsy shop connected. Ask the shop owner to connect their Etsy account.")

    # Resolve or create BuildDraft
    draft_token: str
    if req.draft_token:
        result = await db.execute(
            select(BuildDraft).where(BuildDraft.draft_token == req.draft_token)
        )
        draft = result.scalar_one_or_none()
        if not draft:
            raise HTTPException(status_code=404, detail="Draft not found. Use POST /api/v1/drafts to create one.")
        if req.design_config:
            import json
            draft.design_config = json.dumps(req.design_config)
        draft_token = draft.draft_token
    elif req.design_config:
        import json
        draft_token = secrets.token_urlsafe(32)
        draft = BuildDraft(
            draft_token=draft_token,
            design_config=json.dumps(req.design_config),
        )
        db.add(draft)
        await db.flush()
    else:
        raise HTTPException(status_code=422, detail="Provide either draft_token or design_config.")

    # Get a valid access token (refreshes if expired)
    try:
        access_token = await get_valid_token(seller, creds=creds)
        await db.commit()  # persist any refreshed tokens
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))

    shop_id = seller.etsy_shop_id

    # 1. Create draft listing on Etsy
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

    listing_id: int = listing["listing_id"]
    listing_url = f"https://www.etsy.com/listing/{listing_id}"

    # 2. Upload instruction file and mark listing as digital download
    try:
        from app.services.etsy_client import generate_instruction_file
        instruction_bytes = generate_instruction_file(
            shop_name=seller.etsy_shop_name or "MapForgeDesign",
            frontend_url=settings.FRONTEND_URL or "https://mapforge-production.up.railway.app",
        )
        await upload_listing_file(
            access_token=access_token,
            shop_id=shop_id,
            listing_id=listing_id,
            file_bytes=instruction_bytes,
            filename="MapForge_Your_Custom_Map_Instructions.txt",
            creds=creds,
        )
        await update_listing_type(
            access_token=access_token,
            shop_id=shop_id,
            listing_id=listing_id,
            listing_type="download",
            creds=creds,
        )
    except ValueError as e:
        log.warning("Etsy digital file upload/type-update failed (listing still created): %s", e)

    # 3. Persist the PublishedListing mapping
    pub_listing = PublishedListing(
        etsy_listing_id=str(listing_id),
        build_draft_id=draft.id,
        listing_url=listing_url,
        state="draft",
        status="active",
    )
    db.add(pub_listing)
    await db.commit()

    log.info(
        "Anonymous push-to-Etsy: listing %d created for draft %s (%s)",
        listing_id, draft_token, req.title,
    )

    return EtsyPushResponse(
        draft_token=draft_token,
        listing_id=listing_id,
        listing_url=listing_url,
        status="draft",
    )