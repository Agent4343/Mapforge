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
    png = "png"


class BoardSize(str, Enum):
    small = "small"          # 12x16"
    medium = "medium"        # 16x20"
    large = "large"          # 20x24"
    xl = "xl"                # 24x32"
    max = "max"              # 32x48"
    custom = "custom"
    # Print poster sizes
    print_8x10 = "print_8x10"
    print_11x14 = "print_11x14"
    print_16x20 = "print_16x20"
    print_18x24 = "print_18x24"
    print_24x36 = "print_24x36"


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
    # Print poster sizes
    "print_8x10": (8, 10),
    "print_11x14": (11, 14),
    "print_16x20": (16, 20),
    "print_18x24": (18, 24),
    "print_24x36": (24, 36),
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

class MarkerIcon(str, Enum):
    pin = "pin"
    heart = "heart"
    star = "star"
    home = "home"
    diamond = "diamond"


class MapMarker(BaseModel):
    """A custom location marker to place on a map (e.g. Home, The Cottage)."""
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    label: str = Field("", max_length=60)
    icon: MarkerIcon = MarkerIcon.pin


class FontFamily(str, Enum):
    sans = "sans"         # Arial/Helvetica — clean modern
    serif = "serif"       # Georgia/Times — classic elegant
    script = "script"     # Brush Script — romantic/wedding
    mono = "mono"         # Courier — technical/minimal


class BorderStyle(str, Enum):
    none = "none"
    thin = "thin"         # Simple thin line
    double = "double"     # Double line frame
    ornate = "ornate"     # Decorative corner frame


class OutputMode(str, Enum):
    cnc = "cnc"
    print = "print"


class GenerateRequest(BaseModel):
    osm_id: int
    osm_type: str = "relation"
    product_type: ProductType = ProductType.lake
    board_size: BoardSize = BoardSize.medium
    board_width_inches: Optional[float] = Field(None, gt=1, le=60)
    board_height_inches: Optional[float] = Field(None, gt=1, le=60)
    style: CutStyle = CutStyle.outline
    export_format: ExportFormat = ExportFormat.svg
    output_mode: str = "cnc"  # "cnc" or "print"
    text: str = ""
    subtitle: str = ""  # "Where We Met" / "Est. 2024" / custom tagline
    show_coordinates: bool = True
    font_size_mm: float = Field(14.0, ge=4, le=40)
    font_family: FontFamily = FontFamily.serif
    border_style: BorderStyle = BorderStyle.none
    simplification: str = "auto"
    include_islands: bool = True
    min_island_area_m2: float = Field(5000.0, ge=0)
    include_streets: bool = False
    include_contours: bool = False
    contour_type: str = "elevation"  # elevation or depth
    num_depth_bands: int = Field(5, ge=2, le=10)
    markers: list[MapMarker] = Field(default_factory=list, max_length=10)
    color_theme: str = "classic"  # classic, modern_dark, rose_gold, midnight, sage, minimal
    heart_lat: Optional[float] = Field(None, ge=-90, le=90)
    heart_lon: Optional[float] = Field(None, ge=-180, le=180)

    @field_validator("text")
    @classmethod
    def sanitize_text(cls, v: str) -> str:
        if len(v) > 200:
            v = v[:200]
        # Strip control characters that could cause issues in SVG/XML
        return "".join(c for c in v if c.isprintable() or c in ("\n", "\t"))

    @field_validator("subtitle")
    @classmethod
    def sanitize_subtitle(cls, v: str) -> str:
        if len(v) > 200:
            v = v[:200]
        return "".join(c for c in v if c.isprintable() or c in ("\n", "\t"))


class PinGenerateRequest(BaseModel):
    """Generate a name sign / location marker from coordinates."""
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    label: str = Field("My Place", min_length=1, max_length=200)
    subtitle: str = ""
    board_size: BoardSize = BoardSize.medium
    board_width_inches: Optional[float] = Field(None, gt=1, le=60)
    board_height_inches: Optional[float] = Field(None, gt=1, le=60)
    style: CutStyle = CutStyle.outline
    export_format: ExportFormat = ExportFormat.svg
    show_coordinates: bool = True
    font_size_mm: float = Field(14.0, ge=4, le=40)
    font_family: FontFamily = FontFamily.serif
    border_style: BorderStyle = BorderStyle.none
    radius_m: float = Field(500.0, ge=100, le=5000)
    include_streets: bool = True
    output_mode: str = "cnc"  # "cnc" or "print"
    color_theme: str = "classic"


class GenerateResponse(BaseModel):
    svg: Optional[str] = None
    dxf_available: bool = False
    thumbnail_available: bool = False
    print_png_available: bool = False
    file_id: str
    location_name: str
    dimensions_mm: tuple[float, float]
    node_count: int
    path_count: int
    layer_count: int
    warnings: list[str] = Field(default_factory=list)


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


class UpdateListingRequest(BaseModel):
    price_cents: Optional[int] = Field(None, ge=199, le=9999)
    title: Optional[str] = Field(None, min_length=5, max_length=255)
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
    title: Optional[str] = None
    product_type: Optional[str] = None
    board_width_mm: Optional[float] = None
    board_height_mm: Optional[float] = None
    purchased_at: Optional[str] = None


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
