"""Marketplace router — list, browse, purchase, review, seller dashboard."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.logging_config import log
from app.models.db_models import (
    GeneratedFile, MarketplaceListing, Purchase, Review, User,
)
from app.models.schemas import (
    CreateListingRequest, CreateReviewRequest, ListingResponse,
    MarketplaceResponse, PurchaseRequest, PurchaseResponse,
    ReviewResponse, SellerDashboardResponse, UpdateListingRequest,
)
from app.services.auth import get_current_user, get_optional_user
from app.services.ai_description_generator import generate_full_listing as ai_generate_listing
from app.services.payments import create_payment_intent

router = APIRouter(prefix="/api/v1/marketplace", tags=["marketplace"])


# --- Browse ---

@router.get("", response_model=MarketplaceResponse)
async def browse_marketplace(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    product_type: str | None = None,
    province: str | None = None,
    search: str | None = None,
    sort: str = Query("newest", pattern="^(newest|popular|rating|price_asc|price_desc)$"),
    db: AsyncSession = Depends(get_db),
):
    """Browse marketplace listings."""
    query = (
        select(MarketplaceListing, GeneratedFile, User)
        .join(GeneratedFile, MarketplaceListing.file_id == GeneratedFile.id)
        .join(User, MarketplaceListing.seller_id == User.id)
        .where(MarketplaceListing.is_active == True)
    )

    if product_type:
        query = query.where(GeneratedFile.product_type == product_type)
    if province:
        query = query.where(GeneratedFile.province == province)
    if search:
        query = query.where(MarketplaceListing.title.ilike(f"%{search}%"))

    # Sorting
    if sort == "popular":
        query = query.order_by(MarketplaceListing.sale_count.desc())
    elif sort == "rating":
        query = query.order_by(MarketplaceListing.average_rating.desc())
    elif sort == "price_asc":
        query = query.order_by(MarketplaceListing.price_cents.asc())
    elif sort == "price_desc":
        query = query.order_by(MarketplaceListing.price_cents.desc())
    else:
        query = query.order_by(MarketplaceListing.created_at.desc())

    # Count (apply same filters)
    count_sub = (
        select(MarketplaceListing.id)
        .join(GeneratedFile, MarketplaceListing.file_id == GeneratedFile.id)
        .where(MarketplaceListing.is_active == True)
    )
    if product_type:
        count_sub = count_sub.where(GeneratedFile.product_type == product_type)
    if province:
        count_sub = count_sub.where(GeneratedFile.province == province)
    if search:
        count_sub = count_sub.where(MarketplaceListing.title.ilike(f"%{search}%"))
    count_q = select(func.count()).select_from(count_sub.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    # Paginate
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    rows = result.all()

    listings = []
    for listing, file, seller in rows:
        listing.view_count += 1  # track impressions
        listings.append(_listing_response(listing, file, seller))

    if rows:
        await db.commit()

    return MarketplaceResponse(listings=listings, total=total, page=page, per_page=per_page)


# --- Create Listing ---

@router.post("/list", response_model=ListingResponse, status_code=201)
async def create_listing(
    req: CreateListingRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List a generated file on the marketplace."""
    if user.tier not in ("maker", "pro", "admin"):
        raise HTTPException(status_code=403, detail="Marketplace listing requires Maker or Pro subscription.")

    # Verify file ownership
    result = await db.execute(
        select(GeneratedFile).where(
            GeneratedFile.id == req.file_id,
            GeneratedFile.owner_id == user.id,
        )
    )
    file_record = result.scalar_one_or_none()
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found or not owned by you.")

    # Check not already listed
    existing = await db.execute(
        select(MarketplaceListing).where(MarketplaceListing.file_id == req.file_id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="This file is already listed on the marketplace.")

    listing = MarketplaceListing(
        file_id=req.file_id,
        seller_id=user.id,
        price_cents=req.price_cents,
        title=req.title,
        description=req.description,
        tags=req.tags,
    )
    db.add(listing)
    await db.commit()
    await db.refresh(listing)

    log.info(f"New listing: {listing.id} by {user.username} — {req.title} (${req.price_cents/100:.2f})")

    return _listing_response(listing, file_record, user)


# --- Purchase ---

@router.post("/purchase", response_model=PurchaseResponse)
async def purchase_listing(
    req: PurchaseRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Purchase a marketplace listing."""
    result = await db.execute(
        select(MarketplaceListing).where(
            MarketplaceListing.id == req.listing_id,
            MarketplaceListing.is_active == True,
        )
    )
    listing = result.scalar_one_or_none()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found.")

    if listing.seller_id == user.id:
        raise HTTPException(status_code=400, detail="You cannot purchase your own listing.")

    # Check not already purchased
    existing = await db.execute(
        select(Purchase).where(
            Purchase.listing_id == req.listing_id,
            Purchase.buyer_id == user.id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="You already purchased this file.")

    # Calculate fees
    fee_pct = settings.PLATFORM_FEE_PERCENT_PRO if user.tier in ("pro", "admin") else settings.PLATFORM_FEE_PERCENT_MAKER
    platform_fee = int(listing.price_cents * fee_pct / 100)
    seller_payout = listing.price_cents - platform_fee

    # Record purchase first so we have an ID for payment metadata
    purchase = Purchase(
        listing_id=listing.id,
        buyer_id=user.id,
        price_cents=listing.price_cents,
        platform_fee_cents=platform_fee,
        seller_payout_cents=seller_payout,
        stripe_payment_intent_id="",  # filled after payment created
        status="pending",
    )
    db.add(purchase)
    await db.flush()  # generate ID without committing

    # Create payment with purchase_id in metadata for webhook processing
    payment = await create_payment_intent(
        customer_id=user.stripe_customer_id or "",
        amount_cents=listing.price_cents,
        metadata={
            "listing_id": listing.id,
            "buyer_id": user.id,
            "purchase_id": purchase.id,
        },
    )

    # Update purchase with payment details
    purchase.stripe_payment_intent_id = payment["id"]
    if payment["status"] == "succeeded":
        purchase.status = "completed"
        # sale_count is incremented by the webhook handler to avoid double-counting

    await db.commit()
    await db.refresh(purchase)

    log.info(f"Purchase: {purchase.id} — listing {listing.id} by user {user.username}")

    return PurchaseResponse(
        purchase_id=purchase.id,
        file_id=listing.file_id,
        payment_status=purchase.status,
        client_secret=payment.get("client_secret"),
    )


# --- Reviews ---

@router.post("/review", response_model=ReviewResponse, status_code=201)
async def create_review(
    req: CreateReviewRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Review a purchased listing."""
    # Verify purchase
    purchase_result = await db.execute(
        select(Purchase).where(
            Purchase.listing_id == req.listing_id,
            Purchase.buyer_id == user.id,
            Purchase.status == "completed",
        )
    )
    if not purchase_result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="You must purchase this file before reviewing.")

    # Check not already reviewed
    existing = await db.execute(
        select(Review).where(
            Review.listing_id == req.listing_id,
            Review.buyer_id == user.id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="You already reviewed this listing.")

    review = Review(
        listing_id=req.listing_id,
        buyer_id=user.id,
        rating=req.rating,
        comment=req.comment,
        cnc_compatible=req.cnc_compatible,
    )
    db.add(review)

    # Update listing rating atomically to avoid race conditions
    listing_result = await db.execute(
        select(MarketplaceListing).where(MarketplaceListing.id == req.listing_id)
    )
    listing = listing_result.scalar_one_or_none()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found.")
    total_rating = listing.average_rating * listing.rating_count + req.rating
    listing.rating_count += 1
    listing.average_rating = round(total_rating / listing.rating_count, 2)

    await db.commit()
    await db.refresh(review)

    return ReviewResponse(
        id=review.id,
        rating=review.rating,
        comment=review.comment,
        cnc_compatible=review.cnc_compatible,
        buyer_username=user.username,
        created_at=review.created_at.isoformat(),
    )


@router.get("/reviews/{listing_id}", response_model=list[ReviewResponse])
async def get_reviews(listing_id: str, db: AsyncSession = Depends(get_db)):
    """Get reviews for a listing."""
    result = await db.execute(
        select(Review, User)
        .join(User, Review.buyer_id == User.id)
        .where(Review.listing_id == listing_id)
        .order_by(Review.created_at.desc())
    )
    rows = result.all()
    return [
        ReviewResponse(
            id=review.id,
            rating=review.rating,
            comment=review.comment,
            cnc_compatible=review.cnc_compatible,
            buyer_username=user.username,
            created_at=review.created_at.isoformat(),
        )
        for review, user in rows
    ]


# --- Seller Dashboard ---

@router.get("/dashboard", response_model=SellerDashboardResponse)
async def seller_dashboard(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get seller dashboard stats."""
    # Listings
    listings_result = await db.execute(
        select(MarketplaceListing, GeneratedFile)
        .join(GeneratedFile, MarketplaceListing.file_id == GeneratedFile.id)
        .where(MarketplaceListing.seller_id == user.id)
        .order_by(MarketplaceListing.created_at.desc())
    )
    rows = listings_result.all()

    total_listings = len(rows)
    active_listings = sum(1 for listing, _ in rows if listing.is_active)
    total_sales = sum(listing.sale_count for listing, _ in rows)
    total_views = sum(listing.view_count for listing, _ in rows)

    # Revenue
    revenue_result = await db.execute(
        select(func.sum(Purchase.seller_payout_cents)).where(
            Purchase.listing_id.in_([listing.id for listing, _ in rows]),
            Purchase.status == "completed",
        )
    )
    total_revenue = revenue_result.scalar() or 0

    listings = [
        _listing_response(listing, file, user)
        for listing, file in rows
    ]

    return SellerDashboardResponse(
        total_listings=total_listings,
        active_listings=active_listings,
        total_sales=total_sales,
        total_revenue_cents=total_revenue,
        total_views=total_views,
        listings=listings,
    )


# --- Update Listing ---

@router.patch("/{listing_id}", response_model=ListingResponse)
async def update_listing(
    listing_id: str,
    req: UpdateListingRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a listing's price, title, description, or tags."""
    result = await db.execute(
        select(MarketplaceListing, GeneratedFile)
        .join(GeneratedFile, MarketplaceListing.file_id == GeneratedFile.id)
        .where(
            MarketplaceListing.id == listing_id,
            MarketplaceListing.seller_id == user.id,
        )
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Listing not found.")
    listing, file = row

    if req.price_cents is not None:
        listing.price_cents = req.price_cents
    if req.title is not None:
        listing.title = req.title
    if req.description is not None:
        listing.description = req.description
    if req.tags is not None:
        listing.tags = req.tags

    await db.commit()
    await db.refresh(listing)

    log.info(f"Listing updated: {listing.id} by {user.username}")
    return _listing_response(listing, file, user)


# --- My Purchases ---

@router.get("/purchases", response_model=list[PurchaseResponse])
async def my_purchases(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get current user's purchased files."""
    result = await db.execute(
        select(Purchase, MarketplaceListing, GeneratedFile)
        .join(MarketplaceListing, Purchase.listing_id == MarketplaceListing.id)
        .join(GeneratedFile, MarketplaceListing.file_id == GeneratedFile.id)
        .where(Purchase.buyer_id == user.id, Purchase.status == "completed")
        .order_by(Purchase.created_at.desc())
    )
    rows = result.all()
    return [
        PurchaseResponse(
            purchase_id=purchase.id,
            file_id=listing.file_id,
            payment_status=purchase.status,
            title=listing.title,
            product_type=file.product_type,
            board_width_mm=file.board_width_mm,
            board_height_mm=file.board_height_mm,
            purchased_at=purchase.created_at.isoformat(),
        )
        for purchase, listing, file in rows
    ]


# --- AI Description Generation ---

@router.post("/ai-describe")
async def ai_describe(
    location_name: str = Query(..., min_length=1),
    style: str = Query("filled", pattern="^(filled|outline|engraved)$"),
    country: str = Query("", max_length=20),
    is_city: bool = Query(False),
    province: str = Query("", max_length=50),
    user: User = Depends(get_current_user),
):
    """Generate an AI-written Etsy listing (title + description + tags).

    Requires ANTHROPIC_API_KEY to be configured. Falls back to empty
    values if the AI service is unavailable.
    """
    result = await ai_generate_listing(
        location_name=location_name,
        style=style,
        country=country,
        is_city=is_city,
        province=province,
        has_streets=is_city,
    )

    if not any(result.values()):
        raise HTTPException(
            status_code=503,
            detail="AI description service unavailable. Check ANTHROPIC_API_KEY configuration.",
        )

    return {
        "title": result.get("title"),
        "description": result.get("description"),
        "tags": result.get("tags"),
    }


# --- Remove Listing ---

@router.delete("/{listing_id}", status_code=204)
async def remove_listing(
    listing_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a listing from the marketplace."""
    result = await db.execute(
        select(MarketplaceListing).where(
            MarketplaceListing.id == listing_id,
            MarketplaceListing.seller_id == user.id,
        )
    )
    listing = result.scalar_one_or_none()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found.")

    listing.is_active = False
    await db.commit()


# --- Helpers ---

def _listing_response(listing: MarketplaceListing, file: GeneratedFile, seller: User) -> ListingResponse:
    return ListingResponse(
        id=listing.id,
        file_id=listing.file_id,
        seller_username=seller.username,
        price_cents=listing.price_cents,
        currency=listing.currency,
        title=listing.title,
        description=listing.description,
        tags=listing.tags,
        view_count=listing.view_count,
        sale_count=listing.sale_count,
        average_rating=listing.average_rating,
        rating_count=listing.rating_count,
        product_type=file.product_type,
        board_width_mm=file.board_width_mm,
        board_height_mm=file.board_height_mm,
        province=file.province,
        created_at=listing.created_at.isoformat(),
    )
