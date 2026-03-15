"""Pydantic models for MapForge CNC API requests and responses."""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ProductType(str, Enum):
    lake = "lake"
    province = "province"
    city = "city"
    park = "park"
    name_sign = "name_sign"


class CutStyle(str, Enum):
    outline = "outline"
    filled = "filled"
    engraved = "engraved"


class BoardSize(str, Enum):
    small = "small"          # 12x16"
    medium = "medium"        # 16x20"
    large = "large"          # 20x24"
    xl = "xl"                # 24x32"
    max = "max"              # 32x48"
    custom = "custom"


BOARD_DIMENSIONS_INCHES = {
    "small": (12, 16),
    "medium": (16, 20),
    "large": (20, 24),
    "xl": (24, 32),
    "max": (32, 48),
}


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


class GenerateRequest(BaseModel):
    osm_id: int
    osm_type: str = "relation"
    product_type: ProductType = ProductType.lake
    board_size: BoardSize = BoardSize.medium
    board_width_inches: Optional[float] = None
    board_height_inches: Optional[float] = None
    style: CutStyle = CutStyle.outline
    text: str = ""
    show_coordinates: bool = True
    font_size_mm: float = 14.0
    simplification: str = "auto"
    include_islands: bool = True
    min_island_area_m2: float = 5000.0


class GenerateResponse(BaseModel):
    svg: str
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
