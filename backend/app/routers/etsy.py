"""Etsy integration router — OAuth 2.0 connection and listing publishing."""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.logging_config import log
from app.models.db_models import GeneratedFile, User
from app.models.schemas import GenerateRequest, ProductType, CutStyle, BoardSize, FontFamily
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


async def _ensure_shop_info(user: User, db: AsyncSession, creds: dict | None = None):
    """Lazily fetch and save Etsy shop info if we have a token but no shop_id.

    This handles the case where the OAuth callback succeeded but get_shop()
    failed (e.g. Etsy API timeout). Rather than blocking the user permanently,
    retry fetching shop info when they actually need it.
    """
    if user.etsy_shop_id:
        return  # Already have it

    if not user.etsy_access_token:
        raise HTTPException(status_code=400, detail="Etsy not connected. Connect your shop first.")

    try:
        access_token = await get_valid_token(user, creds=creds)
        await db.commit()  # persist any refreshed tokens
    except ValueError as e:
        log.error("Etsy token refresh failed during shop recovery: %s", e)
        raise HTTPException(
            status_code=401,
            detail=f"Etsy token expired. Please disconnect and reconnect your Etsy account. ({e})",
        )

    try:
        shop = await get_shop(access_token, creds=creds)
        user.etsy_shop_id = str(shop["shop_id"])
        user.etsy_shop_name = shop.get("shop_name", "")
        await db.commit()
        log.info("Recovered Etsy shop info: %s (%s)", user.etsy_shop_name, user.etsy_shop_id)
    except Exception as e:
        log.error("Failed to recover Etsy shop info: %s", e)
        raise HTTPException(
            status_code=400,
            detail=f"Could not fetch your Etsy shop info: {e}",
        )


# --- Schemas ---

class EtsyPublishRequest(BaseModel):
    file_id: str
    title: str = Field(..., max_length=140)
    description: str = Field(..., max_length=5000)
    price: float = Field(..., ge=0.20, le=99.99)
    tags: list[str] = Field(default_factory=list, max_length=13)


class ShowcaseCity(BaseModel):
    name: str
    osm_id: int
    osm_type: str = "relation"
    product_type: str = "city"
    country: str = ""
    province: str = ""


class ShowcasePublishRequest(BaseModel):
    city: ShowcaseCity
    color_theme: str = "classic"
    poster_layout: str = "classic"
    font_family: str = "sans"
    board_size: str = "print_16x20"
    price: float = Field(9.99, ge=0.20, le=99.99)
    title: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[str] = None


class ShowcasePublishResponse(BaseModel):
    listing_id: int
    listing_url: str
    file_id: str
    location_name: str
    status: str = "draft"


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

    # Persist the PKCE verifier to the database so it survives server restarts.
    # The in-memory _pkce_store is set by generate_auth_url; copy it to the user row.
    from app.services.etsy_client import _pkce_store
    verifier = _pkce_store.get(user.id)
    if verifier:
        user.etsy_pkce_verifier = verifier
        await db.commit()

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

    # Restore PKCE verifier from database if not in memory (e.g. after server restart)
    from app.services.etsy_client import _pkce_store
    if user_id not in _pkce_store and user.etsy_pkce_verifier:
        _pkce_store[user_id] = user.etsy_pkce_verifier

    try:
        tokens = await exchange_code(user_id, code, creds=creds)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Clear the stored verifier
    user.etsy_pkce_verifier = None

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
    frontend_url = settings.FRONTEND_URL or "https://mapforge-production.up.railway.app"
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

    # Lazily recover shop info if the callback didn't save it
    await _ensure_shop_info(user, db, creds)

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


# --- Showcase Preset Cities ---

SHOWCASE_CITIES = [
    ShowcaseCity(name="New York City", osm_id=175905, osm_type="relation", product_type="city", country="us", province="New York"),
    ShowcaseCity(name="London", osm_id=65606, osm_type="relation", product_type="city", country="gb", province="England"),
    ShowcaseCity(name="Paris", osm_id=7444, osm_type="relation", product_type="city", country="fr", province="Île-de-France"),
    ShowcaseCity(name="Tokyo", osm_id=1543125, osm_type="relation", product_type="city", country="jp", province="Tokyo"),
    ShowcaseCity(name="Toronto", osm_id=324211, osm_type="relation", product_type="city", country="ca", province="Ontario"),
    ShowcaseCity(name="San Francisco", osm_id=111968, osm_type="relation", product_type="city", country="us", province="California"),
    ShowcaseCity(name="Chicago", osm_id=122604, osm_type="relation", product_type="city", country="us", province="Illinois"),
    ShowcaseCity(name="Sydney", osm_id=5750005, osm_type="relation", product_type="city", country="au", province="New South Wales"),
    ShowcaseCity(name="Amsterdam", osm_id=47811, osm_type="relation", product_type="city", country="nl", province="North Holland"),
    ShowcaseCity(name="Barcelona", osm_id=347950, osm_type="relation", product_type="city", country="es", province="Catalonia"),
    ShowcaseCity(name="Rome", osm_id=41485, osm_type="relation", product_type="city", country="it", province="Lazio"),
    ShowcaseCity(name="Berlin", osm_id=62422, osm_type="relation", product_type="city", country="de", province="Berlin"),
    ShowcaseCity(name="Halifax", osm_id=10178893, osm_type="relation", product_type="city", country="ca", province="Nova Scotia"),
    ShowcaseCity(name="Vancouver", osm_id=1852574, osm_type="relation", product_type="city", country="ca", province="British Columbia"),
    ShowcaseCity(name="Los Angeles", osm_id=207359, osm_type="relation", product_type="city", country="us", province="California"),
    ShowcaseCity(name="Miami", osm_id=1216769, osm_type="relation", product_type="city", country="us", province="Florida"),
]


@router.get("/showcase-cities")
async def get_showcase_cities(user: User = Depends(get_current_user)):
    """Get list of preset showcase cities for quick Etsy publishing. Admin only."""
    if user.tier != "admin":
        raise HTTPException(status_code=403, detail="Admin access required.")
    return [c.model_dump() for c in SHOWCASE_CITIES]


@router.post("/showcase-publish", response_model=ShowcasePublishResponse)
async def showcase_publish(
    req: ShowcasePublishRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a map for a showcase city and publish it to Etsy as a draft listing.

    Admin only. This is a one-click workflow: generate map → AI description → publish to Etsy.
    """
    if user.tier != "admin":
        raise HTTPException(status_code=403, detail="Admin access required.")

    creds = await get_etsy_credentials(db)
    if not is_configured(creds):
        raise HTTPException(status_code=503, detail="Etsy integration is not configured.")
    if not user.etsy_access_token:
        raise HTTPException(status_code=400, detail="Etsy not connected. Connect your shop first.")

    # Lazily recover shop info if the callback didn't save it
    await _ensure_shop_info(user, db, creds)

    city = req.city

    # 1. Generate the map using the same core engine
    from app.routers.generate import _do_generate
    gen_req = GenerateRequest(
        osm_id=city.osm_id,
        osm_type=city.osm_type,
        product_type=ProductType(city.product_type),
        board_size=BoardSize(req.board_size),
        style=CutStyle.filled,
        text=city.name,
        subtitle="",
        show_coordinates=True,
        font_family=FontFamily(req.font_family),
        color_theme=req.color_theme,
        poster_layout=req.poster_layout,
        show_compass=False,
        show_scale_bar=False,
        gradient_water=True,
        land_shadow=True,
        include_streets=True,
        print_dpi=300,
    )

    try:
        gen_result = await _do_generate(gen_req, user, db)
    except HTTPException:
        raise
    except Exception as e:
        log.error("Showcase generation failed for %s: %s", city.name, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Map generation failed for {city.name}: {e}")

    if not gen_result.file_id:
        raise HTTPException(status_code=500, detail="Map generation did not produce a saved file.")

    # 2. Generate AI title/description/tags (or use provided ones)
    title = req.title
    description = req.description
    tags_str = req.tags

    if not title or not description:
        try:
            from app.services.ai_description_generator import generate_full_listing as ai_generate_listing
            ai_result = await ai_generate_listing(
                location_name=city.name,
                style="filled",
                country=city.country,
                is_city=True,
                province=city.province,
                has_streets=True,
            )
            if not title:
                title = ai_result.get("title", f"{city.name} Map Print - City Street Map Poster")
            if not description:
                description = ai_result.get("description", f"Beautiful map poster of {city.name}. High-quality digital download with street-level detail.")
            if not tags_str:
                tags_str = ai_result.get("tags", f"{city.name} map, city map, map print, wall art, poster")
        except Exception as e:
            log.warning("AI description failed for showcase %s: %s", city.name, e)
            if not title:
                title = f"{city.name} Map Print - City Street Map Poster Wall Art"
            if not description:
                description = (
                    f"Beautiful map poster of {city.name}. "
                    "Detailed street-level map art perfect for home decor. "
                    "High-quality digital download includes print-ready PNG and SVG source file. "
                    "Map data © OpenStreetMap contributors."
                )
            if not tags_str:
                tags_str = f"{city.name} map, city map, map print, wall art, poster, street map, home decor"

    tag_list = [t.strip() for t in tags_str.split(",") if t.strip()][:13]

    # 3. Get the generated file record for image uploads
    result = await db.execute(
        select(GeneratedFile).where(GeneratedFile.id == gen_result.file_id)
    )
    file_record = result.scalar_one_or_none()
    if not file_record:
        raise HTTPException(status_code=500, detail="Generated file not found in database.")

    # 4. Get valid Etsy token
    try:
        access_token = await get_valid_token(user, creds=creds)
        await db.commit()
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))

    shop_id = user.etsy_shop_id

    # 5. Create draft listing on Etsy
    try:
        listing = await create_draft_listing(
            access_token=access_token,
            shop_id=shop_id,
            title=title[:140],
            description=description,
            price=req.price,
            tags=tag_list,
            creds=creds,
        )
    except ValueError as e:
        raise HTTPException(status_code=502, detail=f"Etsy API error: {e}")

    listing_id = listing["listing_id"]

    # 6. Upload listing images
    etsy_key = file_record.svg_storage_key.replace("svg/", "etsy/").replace(".svg", "_etsy.png")
    etsy_img = await retrieve_file(etsy_key)
    if etsy_img:
        try:
            await upload_listing_image(
                access_token=access_token,
                shop_id=shop_id,
                listing_id=listing_id,
                image_bytes=etsy_img,
                filename=f"{city.name.replace(' ', '_')}_listing.png",
                creds=creds,
            )
        except ValueError as e:
            log.warning("Showcase image upload failed: %s", e)

    # Upload thumbnail as second image
    if file_record.thumbnail_key:
        thumb_bytes = await retrieve_file(file_record.thumbnail_key)
        if thumb_bytes:
            try:
                await upload_listing_image(
                    access_token=access_token,
                    shop_id=shop_id,
                    listing_id=listing_id,
                    image_bytes=thumb_bytes,
                    filename=f"{city.name.replace(' ', '_')}_mockup.png",
                    rank=2,
                    creds=creds,
                )
            except ValueError as e:
                log.warning("Showcase thumbnail upload failed: %s", e)

    # Upload wall mockup as third image
    try:
        from app.services.thumbnail_generator import generate_wall_mockup
        if file_record.svg_storage_key:
            svg_bytes = await retrieve_file(file_record.svg_storage_key)
            if svg_bytes:
                mockup_bytes = generate_wall_mockup(svg_bytes.decode("utf-8"), style="light_wall")
                await upload_listing_image(
                    access_token=access_token,
                    shop_id=shop_id,
                    listing_id=listing_id,
                    image_bytes=mockup_bytes,
                    filename=f"{city.name.replace(' ', '_')}_wall_mockup.png",
                    rank=3,
                    creds=creds,
                )
    except Exception as e:
        log.warning("Showcase wall mockup upload failed: %s", e)

    # 7. Upload actual map files as digital downloads (pre-made, not instruction file)
    #    Showcase maps are ready-to-print — buyers get the real files immediately.
    file_rank = 1

    # Upload print-ready PNG as primary download
    if file_record.print_png_key:
        print_png_bytes = await retrieve_file(file_record.print_png_key)
        if print_png_bytes:
            try:
                safe_name = city.name.replace(" ", "_").replace(",", "")
                await upload_listing_file(
                    access_token=access_token,
                    shop_id=shop_id,
                    listing_id=listing_id,
                    file_bytes=print_png_bytes,
                    filename=f"{safe_name}_Map_Print_300DPI.png",
                    rank=file_rank,
                    creds=creds,
                )
                file_rank += 1
            except ValueError as e:
                log.warning("Showcase PNG file upload failed: %s", e)

    # Upload SVG source as second download
    if file_record.svg_storage_key:
        svg_bytes = await retrieve_file(file_record.svg_storage_key)
        if svg_bytes:
            try:
                safe_name = city.name.replace(" ", "_").replace(",", "")
                await upload_listing_file(
                    access_token=access_token,
                    shop_id=shop_id,
                    listing_id=listing_id,
                    file_bytes=svg_bytes,
                    filename=f"{safe_name}_Map_Vector.svg",
                    rank=file_rank,
                    creds=creds,
                )
                file_rank += 1
            except ValueError as e:
                log.warning("Showcase SVG file upload failed: %s", e)

    # Mark listing as digital download
    try:
        await update_listing_type(
            access_token=access_token,
            shop_id=shop_id,
            listing_id=listing_id,
            listing_type="download",
            creds=creds,
        )
    except ValueError as e:
        log.warning("Showcase listing type update failed: %s", e)

    listing_url = f"https://www.etsy.com/listing/{listing_id}"
    log.info("Showcase published: %s → Etsy listing %d", city.name, listing_id)

    return ShowcasePublishResponse(
        listing_id=listing_id,
        listing_url=listing_url,
        file_id=gen_result.file_id,
        location_name=city.name,
        status="draft",
    )
