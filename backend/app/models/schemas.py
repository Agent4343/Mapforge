"""Pydantic models for MapForge CNC API requests and responses."""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class ProductType(str, Enum):
    lake = "lake"
    province = "province"
    city = "city"
    community = "community"
    park = "park"
    name_sign = "name_sign"


class CutStyle(str, Enum):
    outline = "outline"
    filled = "filled"
    engraved = "engraved"


class ExportFormat(str, Enum):
    svg = "svg"
    dxf = "dxf"


class BoardSize(str, Enum):
    small = "small"          # 12x16"
    medium = "medium"        # 16x20"
    large = "large"          # 20x24"
    xl = "xl"                # 24x32"
    max = "max"              # 32x48"
    custom = "custom"


class UserTier(str, Enum):
    free = "free"
    maker = "maker"
    pro = "pro"
    admin = "admin"


BOARD_DIMENSIONS_INCHES = {
    "small": (12, 16),
    "medium": (16, 20),
    "large": (20, 24),
    "xl": (24, 32),
    "max": (32, 48),
}


# --- Auth ---

class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=255)
    username: str = Field(..., min_length=3, max_length=100)
    password: str = Field(..., min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: str
    password: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserProfile"


class UserProfile(BaseModel):
    id: str
    email: str
    username: str
    tier: str
    generation_count_this_month: int

    class Config:
        from_attributes = True


# --- Search ---

class SearchResult(BaseModel):
    osm_id: int
    osm_type: str
    display_name: str
    lat: float
    lon: float
    feature_type: str
    boundingbox: list[float] = []
    has_geometry: bool = False


class SearchResponse(BaseModel):
    results: list[SearchResult]
    query: str
    count: int


# --- Generate ---

class GenerateRequest(BaseModel):
    osm_id: int
    osm_type: str = "relation"
    product_type: ProductType = ProductType.lake
    board_size: BoardSize = BoardSize.medium
    board_width_inches: Optional[float] = Field(None, gt=1, le=60)
    board_height_inches: Optional[float] = Field(None, gt=1, le=60)
    style: CutStyle = CutStyle.outline
    export_format: ExportFormat = ExportFormat.svg
    text: str = ""
    show_coordinates: bool = True
    font_size_mm: float = Field(14.0, ge=4, le=40)
    simplification: str = "auto"
    include_islands: bool = True
    min_island_area_m2: float = Field(5000.0, ge=0)
    include_streets: bool = False
    include_contours: bool = False
    contour_type: str = "elevation"  # elevation or depth
    num_depth_bands: int = Field(5, ge=2, le=10)

    @field_validator("text")
    @classmethod
    def sanitize_text(cls, v: str) -> str:
        if len(v) > 200:
            return v[:200]
        return v


class GenerateResponse(BaseModel):
    svg: Optional[str] = None
    dxf_available: bool = False
    thumbnail_available: bool = False
    file_id: str
    location_name: str
    dimensions_mm: tuple[float, float]
    node_count: int
    path_count: int
    layer_count: int


class PreviewResponse(BaseModel):
    svg: str
    location_name: str
    dimensions_mm: tuple[float, float]


# --- Batch Generation ---

class BatchGenerateRequest(BaseModel):
    items: list[GenerateRequest] = Field(..., min_length=1, max_length=50)


class BatchGenerateResponse(BaseModel):
    results: list[GenerateResponse]
    total: int
    succeeded: int
    failed: int


# --- Template Library ---

class LibraryFileResponse(BaseModel):
    id: str
    location_name: str
    display_text: str
    product_type: str
    board_size: str
    board_width_mm: float
    board_height_mm: float
    style: str
    node_count: int
    path_count: int
    province: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    has_dxf: bool = False
    is_listed: bool = False
    created_at: str

    class Config:
        from_attributes = True


class LibraryResponse(BaseModel):
    files: list[LibraryFileResponse]
    total: int
    page: int
    per_page: int


# --- Marketplace ---

class CreateListingRequest(BaseModel):
    file_id: str
    price_cents: int = Field(..., ge=199, le=9999)  # $1.99 – $99.99
    title: str = Field(..., min_length=5, max_length=255)
    description: Optional[str] = Field(None, max_length=2000)
    tags: Optional[str] = Field(None, max_length=500)


class ListingResponse(BaseModel):
    id: str
    file_id: str
    seller_username: str
    price_cents: int
    currency: str
    title: str
    description: Optional[str]
    tags: Optional[str]
    view_count: int
    sale_count: int
    average_rating: float
    rating_count: int
    product_type: str
    board_width_mm: float
    board_height_mm: float
    province: Optional[str]
    created_at: str

    class Config:
        from_attributes = True


class MarketplaceResponse(BaseModel):
    listings: list[ListingResponse]
    total: int
    page: int
    per_page: int


class PurchaseRequest(BaseModel):
    listing_id: str


class PurchaseResponse(BaseModel):
    purchase_id: str
    file_id: str
    payment_status: str
    client_secret: Optional[str] = None


class CreateReviewRequest(BaseModel):
    listing_id: str
    rating: int = Field(..., ge=1, le=5)
    comment: Optional[str] = Field(None, max_length=1000)
    cnc_compatible: bool = True


class ReviewResponse(BaseModel):
    id: str
    rating: int
    comment: Optional[str]
    cnc_compatible: bool
    buyer_username: str
    created_at: str


# --- Seller Dashboard ---

class SellerDashboardResponse(BaseModel):
    total_listings: int
    active_listings: int
    total_sales: int
    total_revenue_cents: int
    total_views: int
    listings: list[ListingResponse]


# --- Subscription ---

class SubscriptionRequest(BaseModel):
    plan: str  # maker_monthly, maker_annual, pro_monthly, pro_annual
    success_url: str
    cancel_url: str


class SubscriptionResponse(BaseModel):
    checkout_url: str
