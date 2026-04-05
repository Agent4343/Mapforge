"""PNG image generator for product mockups and print-ready wall art.

Converts SVG output to PNG images in multiple modes:
- Thumbnail: 2000px for Etsy/Shopify listings
- Print: 4800px+ (300/600 DPI) for wall art printing
- Etsy Listing: 2700x2025 (4:3 ratio for grid display)
- Wall Mockup: Framed poster on a wall for lifestyle product photos
- Watermarked: Preview with tiled watermark overlay

Uses cairosvg for SVG-to-PNG rasterization with color remapping
to transform CNC toolpath colors into rich, natural print colors.
"""

import math
import re

import cairosvg

# Regex to strip crop marks group from SVG before rasterizing for previews/listings
_CROP_MARKS_RE = re.compile(r'<g\s+id="crop_marks"[^>]*>.*?</g>', re.DOTALL)


def _strip_crop_marks(svg_string: str) -> str:
    """Remove crop marks from SVG for display images (thumbnails, listings, previews)."""
    return _CROP_MARKS_RE.sub('', svg_string)

# --- Production print constants ---
PRINT_DPI_STANDARD = 300
PRINT_DPI_HIGH = 600

# Etsy listing image dimensions (4:3 ratio for grid display)
ETSY_LISTING_WIDTH = 2700
ETSY_LISTING_HEIGHT = 2025
ETSY_SQUARE_SIZE = 2000

# Print size to pixel dimensions at 300 DPI
PRINT_SIZE_PIXELS = {
    "print_8x10": (2400, 3000),
    "print_11x14": (3300, 4200),
    "print_16x20": (4800, 6000),
    "print_18x24": (5400, 7200),
    "print_24x36": (7200, 10800),
}

# CNC toolpath colors → Professional print colors
# Maps the dark CNC-optimized colors to rich natural tones for wall art
PRINT_COLOR_MAP = {
    # Land / geography fill
    "#2a2a2a": "#4a7c59",  # dark gray → forest green
    "#1a1a1a": "#2d5016",  # near-black stroke → dark green outline
    # Water features
    "#d4e6f1": "#6db3d4",  # pale blue fill → rich lake blue
    "#7fb3d3": "#3a8fbf",  # blue stroke → deeper water blue
    # Streets
    "#333333": "#8b7355",  # dark gray major roads → warm brown
    "#555555": "#a89279",  # medium gray minor roads → light brown
    # Street labels
    "#444444": "#5c4a32",  # dark gray text → brown text
    # Board outline
    "#cccccc": "#d4c5a9",  # light gray → warm tan
    # Text
    "#666666": "#6b5b47",  # coordinate text → warm dark tone
}

# Print poster theme colors — used directly by generate_svg in print mode.
# Each theme has semantic colors for land, water, streets, and text
# so the SVG generator can produce proper poster-style output.
COLOR_THEMES = {
    "classic": {
        "label": "Classic",
        "background": "#faf8f5",
        "colors": PRINT_COLOR_MAP,
        "poster": {
            "mat": "#ffffff",
            "map_bg": "#faf6f0",
            "land": "#d8c8a8",
            "land_stroke": "#a89060",
            "water": "#7ab0d8",
            "water_stroke": "#3a80b8",
            "street_major": "#1a1a1a",
            "street_minor": "#404040",
            "street_label": "#1a1a1a",
            "text_primary": "#1a1a1a",
            "text_secondary": "#555555",
        },
    },
    "modern_dark": {
        "label": "Modern Dark",
        "background": "#1a1a2e",
        "colors": {
            "#2a2a2a": "#2d3748",
            "#1a1a1a": "#4a5568",
            "#d4e6f1": "#2b6cb0",
            "#7fb3d3": "#3182ce",
            "#333333": "#e2e8f0",
            "#555555": "#a0aec0",
            "#444444": "#cbd5e0",
            "#cccccc": "#2d3748",
            "#666666": "#a0aec0",
        },
        "poster": {
            "mat": "#ffffff",
            "map_bg": "#12122a",
            "land": "#1e2050",
            "land_stroke": "#384080",
            "water": "#142860",
            "water_stroke": "#3060b0",
            "street_major": "#f0f4f8",
            "street_minor": "#b0bcd0",
            "street_label": "#d0d8e8",
            "text_primary": "#1a1a1a",
            "text_secondary": "#666666",
        },
    },
    "rose_gold": {
        "label": "Rose Gold",
        "background": "#fdf2f0",
        "colors": {
            "#2a2a2a": "#d4a59a",
            "#1a1a1a": "#c08b7f",
            "#d4e6f1": "#b8d4e3",
            "#7fb3d3": "#7ca8c4",
            "#333333": "#8b6f66",
            "#555555": "#a89080",
            "#444444": "#6b5550",
            "#cccccc": "#e8d5cf",
            "#666666": "#8b6f66",
        },
        "poster": {
            "mat": "#ffffff",
            "map_bg": "#fdf2f0",
            "land": "#f0d4cc",
            "land_stroke": "#c89080",
            "water": "#b8d0e0",
            "water_stroke": "#80a8c4",
            "street_major": "#6b4a40",
            "street_minor": "#9a7a70",
            "street_label": "#5a3d35",
            "text_primary": "#3d2e2a",
            "text_secondary": "#8b6f66",
        },
    },
    "midnight": {
        "label": "Midnight Blue",
        "background": "#0f1923",
        "colors": {
            "#2a2a2a": "#1b3a4b",
            "#1a1a1a": "#3d7ea6",
            "#d4e6f1": "#1a4971",
            "#7fb3d3": "#2980b9",
            "#333333": "#c9d6df",
            "#555555": "#8fa7b8",
            "#444444": "#a8c4d4",
            "#cccccc": "#1b3a4b",
            "#666666": "#8fa7b8",
        },
        "poster": {
            "mat": "#ffffff",
            "map_bg": "#0a1420",
            "land": "#142840",
            "land_stroke": "#1e4068",
            "water": "#081e38",
            "water_stroke": "#1a50a0",
            "street_major": "#d8e4f0",
            "street_minor": "#9ab4c8",
            "street_label": "#b8d0e0",
            "text_primary": "#1a1a1a",
            "text_secondary": "#555555",
        },
    },
    "sage": {
        "label": "Sage Green",
        "background": "#f5f7f2",
        "colors": {
            "#2a2a2a": "#7d9b76",
            "#1a1a1a": "#5a7a52",
            "#d4e6f1": "#a3c4bc",
            "#7fb3d3": "#6b9e91",
            "#333333": "#4a5e44",
            "#555555": "#6b7f65",
            "#444444": "#3d4e38",
            "#cccccc": "#c5d3be",
            "#666666": "#5a6e54",
        },
        "poster": {
            "mat": "#ffffff",
            "map_bg": "#f0f4ec",
            "land": "#d0dcc4",
            "land_stroke": "#a0b890",
            "water": "#a8ccc0",
            "water_stroke": "#6ea898",
            "street_major": "#2a4024",
            "street_minor": "#587850",
            "street_label": "#2a3a24",
            "text_primary": "#2a3528",
            "text_secondary": "#5a6e54",
        },
    },
    "minimal": {
        "label": "Minimal B&W",
        "background": "#ffffff",
        "colors": {
            "#2a2a2a": "#e0e0e0",
            "#1a1a1a": "#333333",
            "#d4e6f1": "#f0f0f0",
            "#7fb3d3": "#999999",
            "#333333": "#222222",
            "#555555": "#666666",
            "#444444": "#444444",
            "#cccccc": "#e8e8e8",
            "#666666": "#888888",
        },
        "poster": {
            "mat": "#ffffff",
            "map_bg": "#fafafa",
            "land": "#e8e8e8",
            "land_stroke": "#a0a0a0",
            "water": "#c8c8c8",
            "water_stroke": "#909090",
            "street_major": "#111111",
            "street_minor": "#404040",
            "street_label": "#222222",
            "text_primary": "#111111",
            "text_secondary": "#555555",
        },
    },
    "navy_gold": {
        "label": "Navy & Gold",
        "background": "#0a1628",
        "colors": {
            "#2a2a2a": "#1a2d52",
            "#1a1a1a": "#d4a843",
            "#d4e6f1": "#1a3a5c",
            "#7fb3d3": "#2c5f8a",
            "#333333": "#d4a843",
            "#555555": "#b8943a",
            "#444444": "#e8c95a",
            "#cccccc": "#1a2d52",
            "#666666": "#c9b06b",
        },
        "poster": {
            "mat": "#ffffff",
            "map_bg": "#081020",
            "land": "#101e3a",
            "land_stroke": "#1a3060",
            "water": "#060e30",
            "water_stroke": "#143870",
            "street_major": "#e8b840",
            "street_minor": "#c8a030",
            "street_label": "#f0d060",
            "text_primary": "#1a1a1a",
            "text_secondary": "#555555",
        },
    },
    "blush": {
        "label": "Blush Pink",
        "background": "#fef0f0",
        "colors": {
            "#2a2a2a": "#e8b4b4",
            "#1a1a1a": "#c27c7c",
            "#d4e6f1": "#f0d4d4",
            "#7fb3d3": "#d4a0a0",
            "#333333": "#c27c7c",
            "#555555": "#d4a0a0",
            "#444444": "#8b5e5e",
            "#cccccc": "#f0d4d4",
            "#666666": "#a87070",
        },
        "poster": {
            "mat": "#ffffff",
            "map_bg": "#fef0f0",
            "land": "#f0cece",
            "land_stroke": "#d89898",
            "water": "#dcc0c8",
            "water_stroke": "#c08898",
            "street_major": "#6b3a3a",
            "street_minor": "#a06060",
            "street_label": "#5a3030",
            "text_primary": "#3d2828",
            "text_secondary": "#8b5e5e",
        },
    },
    "ocean": {
        "label": "Ocean Blue",
        "background": "#e8f4f8",
        "colors": {
            "#2a2a2a": "#5dade2",
            "#1a1a1a": "#1a5276",
            "#d4e6f1": "#85c1e9",
            "#7fb3d3": "#3498db",
            "#333333": "#1a5276",
            "#555555": "#2980b9",
            "#444444": "#0e3d5c",
            "#cccccc": "#aed6f1",
            "#666666": "#1a5276",
        },
        "poster": {
            "mat": "#ffffff",
            "map_bg": "#e8f4f8",
            "land": "#c0dce8",
            "land_stroke": "#78b0d0",
            "water": "#90c4e0",
            "water_stroke": "#4090cc",
            "street_major": "#0e3d5c",
            "street_minor": "#1a6090",
            "street_label": "#082838",
            "text_primary": "#0e3d5c",
            "text_secondary": "#1a5276",
        },
    },
    "charcoal": {
        "label": "Charcoal",
        "background": "#2d2d2d",
        "colors": {
            "#2a2a2a": "#4a4a4a",
            "#1a1a1a": "#e0d5c1",
            "#d4e6f1": "#3d3d3d",
            "#7fb3d3": "#5a5a5a",
            "#333333": "#e0d5c1",
            "#555555": "#b8a88a",
            "#444444": "#d4c5a9",
            "#cccccc": "#4a4a4a",
            "#666666": "#c4b896",
        },
        "poster": {
            "mat": "#ffffff",
            "map_bg": "#252525",
            "land": "#363636",
            "land_stroke": "#505050",
            "water": "#1e1e1e",
            "water_stroke": "#3a3a3a",
            "street_major": "#f0e8d4",
            "street_minor": "#c8b890",
            "street_label": "#e0d4b8",
            "text_primary": "#1a1a1a",
            "text_secondary": "#555555",
        },
    },
    "terracotta": {
        "label": "Terracotta",
        "background": "#faf0e6",
        "colors": {
            "#2a2a2a": "#cd7f50",
            "#1a1a1a": "#8b4513",
            "#d4e6f1": "#deb887",
            "#7fb3d3": "#b87333",
            "#333333": "#8b4513",
            "#555555": "#a0522d",
            "#444444": "#6b3410",
            "#cccccc": "#deb887",
            "#666666": "#8b5e3c",
        },
        "poster": {
            "mat": "#ffffff",
            "map_bg": "#f5e6d6",
            "land": "#e4ccb0",
            "land_stroke": "#c0986c",
            "water": "#b8ccd8",
            "water_stroke": "#789cb0",
            "street_major": "#6b3010",
            "street_minor": "#8b4820",
            "street_label": "#502008",
            "text_primary": "#3d2010",
            "text_secondary": "#8b5e3c",
        },
    },
    "lavender": {
        "label": "Lavender",
        "background": "#f3f0ff",
        "colors": {
            "#2a2a2a": "#b8a9d4",
            "#1a1a1a": "#5b4a8a",
            "#d4e6f1": "#d4ccf0",
            "#7fb3d3": "#9b8ec0",
            "#333333": "#5b4a8a",
            "#555555": "#7b6ba0",
            "#444444": "#3d2e6b",
            "#cccccc": "#d4ccf0",
            "#666666": "#6b5a9a",
        },
        "poster": {
            "mat": "#ffffff",
            "map_bg": "#f0edf8",
            "land": "#d8d0e8",
            "land_stroke": "#b0a0c8",
            "water": "#c4bae0",
            "water_stroke": "#9080b8",
            "street_major": "#3d2e6b",
            "street_minor": "#604e90",
            "street_label": "#2a1e50",
            "text_primary": "#2a2040",
            "text_secondary": "#6b5a9a",
        },
    },
    "forest": {
        "label": "Forest",
        "background": "#0d1f0d",
        "colors": {
            "#2a2a2a": "#1a4a1a",
            "#1a1a1a": "#c4b896",
            "#d4e6f1": "#1a3a1a",
            "#7fb3d3": "#2d6b2d",
            "#333333": "#c4b896",
            "#555555": "#a0956b",
            "#444444": "#d4c5a0",
            "#cccccc": "#1a4a1a",
            "#666666": "#b8a882",
        },
        "poster": {
            "mat": "#ffffff",
            "map_bg": "#081808",
            "land": "#122012",
            "land_stroke": "#1e4a1e",
            "water": "#061006",
            "water_stroke": "#143014",
            "street_major": "#d8cca0",
            "street_minor": "#b0a470",
            "street_label": "#e0d4b0",
            "text_primary": "#1a1a1a",
            "text_secondary": "#555555",
        },
    },
    "sunset": {
        "label": "Sunset",
        "background": "#fff5eb",
        "colors": {
            "#2a2a2a": "#e67e22",
            "#1a1a1a": "#c0392b",
            "#d4e6f1": "#f5cba7",
            "#7fb3d3": "#e59866",
            "#333333": "#c0392b",
            "#555555": "#d35400",
            "#444444": "#922b21",
            "#cccccc": "#f5cba7",
            "#666666": "#a93226",
        },
        "poster": {
            "mat": "#ffffff",
            "map_bg": "#fff5eb",
            "land": "#f0d8b8",
            "land_stroke": "#d8b080",
            "water": "#dcc8b0",
            "water_stroke": "#c0a080",
            "street_major": "#a02818",
            "street_minor": "#b84000",
            "street_label": "#7a2018",
            "text_primary": "#4a1a10",
            "text_secondary": "#a93226",
        },
    },
    "arctic": {
        "label": "Arctic",
        "background": "#f0f8ff",
        "colors": {
            "#2a2a2a": "#85c1e9",
            "#1a1a1a": "#2c3e50",
            "#d4e6f1": "#d6eaf8",
            "#7fb3d3": "#5dade2",
            "#333333": "#2c3e50",
            "#555555": "#34495e",
            "#444444": "#1a252f",
            "#cccccc": "#aed6f1",
            "#666666": "#2c3e50",
        },
        "poster": {
            "mat": "#ffffff",
            "map_bg": "#f0f6fc",
            "land": "#d4e4f0",
            "land_stroke": "#98c0dc",
            "water": "#b8d8f0",
            "water_stroke": "#68aee0",
            "street_major": "#1a2838",
            "street_minor": "#2c4050",
            "street_label": "#101c28",
            "text_primary": "#1a252f",
            "text_secondary": "#2c3e50",
        },
    },
    "vintage_map": {
        "label": "Vintage Map",
        "background": "#f0e6d0",
        "colors": {
            "#2a2a2a": "#d8c8a8",
            "#1a1a1a": "#2a2018",
            "#d4e6f1": "#e8dcc4",
            "#7fb3d3": "#3a3020",
            "#333333": "#2a2018",
            "#555555": "#4a3828",
            "#444444": "#2a2018",
            "#cccccc": "#c8b890",
            "#666666": "#4a3828",
        },
        "poster": {
            "mat": "#f0e6d0",
            "map_bg": "#f0e6d0",
            "land": "#f0e6d0",
            "land_stroke": "#4a3828",
            "water": "#f0e6d0",
            "water_stroke": "#3a3020",
            "street_major": "#2a2018",
            "street_minor": "#4a3828",
            "street_label": "#2a2018",
            "text_primary": "#2a2018",
            "text_secondary": "#4a3828",
        },
    },
    "city_art": {
        "label": "City Map Art",
        "background": "#E8E8E8",
        "colors": {
            "#2a2a2a": "#E8E8E8",
            "#1a1a1a": "#AAAAAA",
            "#d4e6f1": "#D0D0D0",
            "#7fb3d3": "#D0D0D0",
            "#333333": "#1A1A1A",
            "#555555": "#888888",
            "#444444": "#1A1A1A",
            "#cccccc": "#AAAAAA",
            "#666666": "#333333",
        },
        "poster": {
            "mat": "#F0F0F0",
            "map_bg": "#FFFFFF",
            "land": "#FFFFFF",
            "land_stroke": "#BBBBBB",
            "water": "#D0D0D0",
            "water_stroke": "#C0C0C0",
            "street_major": "#1A1A1A",
            "street_minor": "#888888",
            "street_label": "#1A1A1A",
            "text_primary": "#000000",
            "text_secondary": "#333333",
        },
    },
}


def get_theme_colors(theme_name: str) -> dict:
    """Get color map for a theme. Falls back to classic."""
    resolved = _THEME_ALIASES.get(theme_name, theme_name)
    theme = COLOR_THEMES.get(resolved, COLOR_THEMES["classic"])
    return theme["colors"]


def get_theme_background(theme_name: str) -> str:
    """Get background color for a theme."""
    resolved = _THEME_ALIASES.get(theme_name, theme_name)
    theme = COLOR_THEMES.get(resolved, COLOR_THEMES["classic"])
    return theme["background"]


_THEME_ALIASES = {
    "city_map_art": "city_art",
    "cityart": "city_art",
}


def get_poster_theme(theme_name: str) -> dict:
    """Get poster-specific color palette for print-mode SVG generation."""
    resolved = _THEME_ALIASES.get(theme_name, theme_name)
    theme = COLOR_THEMES.get(resolved, COLOR_THEMES["classic"])
    return theme.get("poster", COLOR_THEMES["classic"]["poster"])


def remap_poster_theme(svg_string: str, source_theme: str, target_theme: str) -> str:
    """Remap a print-mode SVG from one poster theme to another.

    The print SVG has poster theme colors baked in (mat, map_bg, land, water,
    streets, text). This replaces every source color with the corresponding
    target color, producing a new themed SVG without re-running geometry.
    """
    src = get_poster_theme(source_theme)
    dst = get_poster_theme(target_theme)
    result = svg_string
    for key in ("mat", "map_bg", "land", "land_stroke", "water", "water_stroke",
                "street_major", "street_minor", "street_label",
                "text_primary", "text_secondary"):
        old = src.get(key, "")
        new = dst.get(key, "")
        if old and new and old != new:
            result = result.replace(f'"{old}"', f'"{new}"')
            result = result.replace(f'"{old.upper()}"', f'"{new}"')
    return result


def remap_svg_colors(svg_string: str, theme_name: str) -> str:
    """Apply a color theme to an SVG string for print preview."""
    colors = get_theme_colors(theme_name)
    bg = get_theme_background(theme_name)
    result = _remap_colors(svg_string, colors)
    result = _add_background(result, bg)
    return result


def generate_thumbnail(
    svg_string: str,
    output_width: int = 2000,
    background_color: str | None = "#f5f0e8",
) -> bytes:
    """Render SVG to a PNG thumbnail image for product listings.

    Args:
        svg_string: The SVG content to render.
        output_width: Pixel width of the output PNG (height scales proportionally).
        background_color: CSS color for the background. None = SVG already has background.

    Returns:
        PNG image as bytes.
    """
    clean_svg = _strip_crop_marks(svg_string)
    styled_svg = _add_background(clean_svg, background_color) if background_color else clean_svg

    png_bytes = cairosvg.svg2png(
        bytestring=styled_svg.encode("utf-8"),
        output_width=output_width,
    )
    return png_bytes


def generate_print_image(
    svg_string: str,
    output_width: int = 4800,
    background_color: str | None = None,
    color_theme: str = "classic",
    skip_remap: bool = False,
    board_size: str | None = None,
    dpi: int = PRINT_DPI_STANDARD,
) -> bytes:
    """Render SVG to a high-resolution print-ready PNG for wall art.

    When skip_remap=True, the SVG is assumed to already have themed colors
    (e.g., from the print-mode SVG generator) and is rasterized directly.

    When skip_remap=False (legacy), CNC toolpath colors are remapped to
    print-friendly colors.

    Args:
        svg_string: The SVG content to render.
        output_width: Pixel width (4800 = 300 DPI at 16"). Use 6000 for 20".
        background_color: Background color override. If None, uses theme default.
        color_theme: Color theme name (classic, modern_dark, rose_gold, etc.).
        skip_remap: If True, skip color remapping (SVG already themed).
        board_size: Board size key (e.g. "print_16x20") for DPI-accurate rendering.
        dpi: Target DPI (300 or 600). Used with board_size for pixel calculation.

    Returns:
        High-resolution PNG image as bytes.
    """
    if skip_remap:
        # Print-mode SVG already has all colors, backgrounds, and layout
        print_svg = svg_string
    else:
        colors = get_theme_colors(color_theme)
        bg = background_color or get_theme_background(color_theme)
        print_svg = _remap_colors(svg_string, colors)
        print_svg = _add_background(print_svg, bg)

    # Calculate DPI-accurate output width when board_size is provided
    if board_size and board_size in PRINT_SIZE_PIXELS:
        base_w, base_h = PRINT_SIZE_PIXELS[board_size]
        scale = dpi / PRINT_DPI_STANDARD
        output_width = int(base_w * scale)

    png_bytes = cairosvg.svg2png(
        bytestring=print_svg.encode("utf-8"),
        output_width=output_width,
    )
    return png_bytes


def _remap_colors(svg_string: str, color_map: dict[str, str]) -> str:
    """Replace CNC toolpath colors with print-friendly colors."""
    result = svg_string
    for old_color, new_color in color_map.items():
        # Replace in fill="..." and stroke="..." attributes (case-insensitive hex)
        result = result.replace(f'fill="{old_color}"', f'fill="{new_color}"')
        result = result.replace(f'stroke="{old_color}"', f'stroke="{new_color}"')
        result = result.replace(f'fill="{old_color.upper()}"', f'fill="{new_color}"')
        result = result.replace(f'stroke="{old_color.upper()}"', f'stroke="{new_color}"')
    return result


def _add_background(svg_string: str, color: str) -> str:
    """Insert a background rectangle right after the opening <svg> tag."""
    start = svg_string.find("<svg")
    if start == -1:
        return svg_string
    svg_open_end = svg_string.find(">", start)
    if svg_open_end == -1:
        return svg_string

    vb_width, vb_height = _parse_viewbox(svg_string)

    bg_rect = (
        f'\n  <rect width="{vb_width}" height="{vb_height}"'
        f' fill="{color}" />'
    )

    return svg_string[: svg_open_end + 1] + bg_rect + svg_string[svg_open_end + 1 :]


def _parse_viewbox(svg_string: str) -> tuple[str, str]:
    """Extract width and height from the viewBox attribute."""
    match = re.search(r'viewBox="([^"]+)"', svg_string)
    if match:
        parts = match.group(1).split()
        if len(parts) == 4:
            return parts[2], parts[3]

    w_match = re.search(r'width="([0-9.]+)', svg_string)
    h_match = re.search(r'height="([0-9.]+)', svg_string)
    w = w_match.group(1) if w_match else "100%"
    h = h_match.group(1) if h_match else "100%"
    return w, h


def generate_etsy_listing_image(
    svg_string: str,
    output_width: int = ETSY_LISTING_WIDTH,
    output_height: int = ETSY_LISTING_HEIGHT,
) -> bytes:
    """Render SVG to a 2700x2025 PNG optimized for Etsy's 4:3 listing grid.

    Etsy displays listing thumbnails at 4:3 ratio. This renders the map
    at 2700px wide so it looks crisp on retina screens in search results.

    Args:
        svg_string: The SVG content to render (should be a themed print SVG).
        output_width: Pixel width for the listing image.
        output_height: Pixel height for the listing image.

    Returns:
        PNG image as bytes sized for Etsy listings.
    """
    clean_svg = _strip_crop_marks(svg_string)
    png_bytes = cairosvg.svg2png(
        bytestring=clean_svg.encode("utf-8"),
        output_width=output_width,
        output_height=output_height,
    )
    return png_bytes


def generate_watermarked_preview(
    svg_string: str,
    output_width: int = 2000,
    watermark_text: str = "MAPFORGE PREVIEW",
) -> bytes:
    """Render SVG to a PNG with a diagonal watermark overlay.

    Used for social media previews and non-purchasable samples so the
    design is visible but not usable as a final product.

    Args:
        svg_string: The SVG content to render.
        output_width: Pixel width of the output PNG.
        watermark_text: Text to tile diagonally across the image.

    Returns:
        Watermarked PNG image as bytes.
    """
    clean_svg = _strip_crop_marks(svg_string)
    watermarked_svg = _add_watermark_to_svg(clean_svg, watermark_text)
    png_bytes = cairosvg.svg2png(
        bytestring=watermarked_svg.encode("utf-8"),
        output_width=output_width,
    )
    return png_bytes


def calculate_print_pixels(
    width_inches: float,
    height_inches: float,
    dpi: int = PRINT_DPI_STANDARD,
) -> tuple[int, int]:
    """Calculate pixel dimensions from physical size and DPI.

    Args:
        width_inches: Print width in inches.
        height_inches: Print height in inches.
        dpi: Dots per inch (300 standard, 600 high).

    Returns:
        Tuple of (width_pixels, height_pixels).
    """
    return (int(math.ceil(width_inches * dpi)), int(math.ceil(height_inches * dpi)))


def _add_watermark_to_svg(
    svg_string: str,
    watermark_text: str = "MAPFORGE PREVIEW",
) -> str:
    """Inject tiled diagonal watermark text into an SVG string.

    Creates a repeating pattern of rotated semi-transparent text
    across the entire SVG canvas, making the output unsuitable for
    commercial use while keeping the design clearly visible.

    Args:
        svg_string: The SVG content to watermark.
        watermark_text: Text to display in the watermark pattern.

    Returns:
        Modified SVG string with watermark overlay.
    """
    vb_width, vb_height = _parse_viewbox(svg_string)

    try:
        w = float(vb_width)
        h = float(vb_height)
    except (ValueError, TypeError):
        w, h = 400.0, 500.0

    font_size = max(w, h) * 0.06
    spacing_x = font_size * 5
    spacing_y = font_size * 3

    watermark_lines = []
    watermark_lines.append(
        '  <g id="watermark" opacity="0.15" '
        'transform="rotate(-30, {cx}, {cy})">'.format(cx=round(w / 2, 2), cy=round(h / 2, 2))
    )

    # Tile watermark text across a larger area to cover rotation
    rows = int(math.ceil(h * 2 / spacing_y)) + 4
    cols = int(math.ceil(w * 2 / spacing_x)) + 4

    for row in range(-2, rows):
        for col in range(-2, cols):
            x = round(col * spacing_x - w * 0.5, 2)
            y = round(row * spacing_y - h * 0.3, 2)
            watermark_lines.append(
                f'    <text x="{x}" y="{y}" '
                f'font-family="Arial, Helvetica, sans-serif" '
                f'font-size="{round(font_size, 1)}" '
                f'font-weight="bold" '
                f'fill="#000000">{watermark_text}</text>'
            )

    watermark_lines.append("  </g>")
    watermark_block = "\n".join(watermark_lines)

    # Insert just before </svg>
    close_idx = svg_string.rfind("</svg>")
    if close_idx == -1:
        return svg_string + "\n" + watermark_block

    return svg_string[:close_idx] + "\n" + watermark_block + "\n" + svg_string[close_idx:]


# --- Wall Mockup Styles ---
# Each style defines wall color, frame color/width, and shadow properties.
MOCKUP_STYLES = {
    "light_wall": {
        "label": "Light Wall",
        "wall_color": "#e8e0d4",
        "wall_texture_color": "#ddd6c8",
        "frame_color": "#1a1a1a",
        "frame_width_pct": 0.015,
        "mat_color": "#ffffff",
        "mat_width_pct": 0.02,
        "shadow_opacity": 0.25,
    },
    "dark_wall": {
        "label": "Dark Wall",
        "wall_color": "#2a2a2a",
        "wall_texture_color": "#333333",
        "frame_color": "#f5f0e8",
        "frame_width_pct": 0.015,
        "mat_color": "#ffffff",
        "mat_width_pct": 0.02,
        "shadow_opacity": 0.4,
    },
    "white_wall": {
        "label": "White Wall",
        "wall_color": "#f5f3ef",
        "wall_texture_color": "#ece8e1",
        "frame_color": "#2c2c2c",
        "frame_width_pct": 0.012,
        "mat_color": "#ffffff",
        "mat_width_pct": 0.018,
        "shadow_opacity": 0.2,
    },
    "brick_wall": {
        "label": "Brick Wall",
        "wall_color": "#8b6f5e",
        "wall_texture_color": "#7d6352",
        "frame_color": "#1a1a1a",
        "frame_width_pct": 0.018,
        "mat_color": "#ffffff",
        "mat_width_pct": 0.022,
        "shadow_opacity": 0.35,
    },
}


def generate_wall_mockup(
    svg_string: str,
    output_width: int = 3000,
    output_height: int = 2400,
    mockup_style: str = "light_wall",
) -> bytes:
    """Generate a lifestyle wall mockup — map poster framed on a wall.

    Creates an SVG scene with a textured wall background, realistic frame
    with mat, drop shadow, and the map poster embedded inside. The scene
    is then rasterized to a high-resolution PNG suitable for Etsy listing
    photos and social media.

    Args:
        svg_string: The poster SVG content to place in the frame.
        output_width: Pixel width of the output mockup image.
        output_height: Pixel height of the output mockup image.
        mockup_style: One of 'light_wall', 'dark_wall', 'white_wall', 'brick_wall'.

    Returns:
        PNG image as bytes.
    """
    style = MOCKUP_STYLES.get(mockup_style, MOCKUP_STYLES["light_wall"])
    clean_svg = _strip_crop_marks(svg_string)

    # Parse the poster's aspect ratio from its viewBox
    poster_vb_w, poster_vb_h = _parse_viewbox(clean_svg)
    try:
        poster_w = float(poster_vb_w)
        poster_h = float(poster_vb_h)
    except (ValueError, TypeError):
        poster_w, poster_h = 400.0, 500.0

    poster_aspect = poster_w / poster_h

    # Scene dimensions (internal SVG units)
    scene_w = 1000
    scene_h = 800

    # Frame sizing — poster fills ~55% of the scene height
    frame_w_pct = style["frame_width_pct"]
    mat_w_pct = style["mat_width_pct"]
    poster_display_h = scene_h * 0.55
    poster_display_w = poster_display_h * poster_aspect

    # If poster is too wide, constrain by width instead
    if poster_display_w > scene_w * 0.6:
        poster_display_w = scene_w * 0.6
        poster_display_h = poster_display_w / poster_aspect

    # Frame and mat dimensions
    frame_thickness = scene_h * frame_w_pct
    mat_thickness = scene_h * mat_w_pct

    total_w = poster_display_w + 2 * (frame_thickness + mat_thickness)
    total_h = poster_display_h + 2 * (frame_thickness + mat_thickness)

    # Center the framed poster in the scene, slightly above center
    frame_x = round((scene_w - total_w) / 2, 2)
    frame_y = round((scene_h - total_h) / 2 - scene_h * 0.03, 2)

    # Inner positions
    mat_x = round(frame_x + frame_thickness, 2)
    mat_y = round(frame_y + frame_thickness, 2)
    mat_inner_w = round(total_w - 2 * frame_thickness, 2)
    mat_inner_h = round(total_h - 2 * frame_thickness, 2)

    poster_x = round(mat_x + mat_thickness, 2)
    poster_y = round(mat_y + mat_thickness, 2)
    poster_render_w = round(poster_display_w, 2)
    poster_render_h = round(poster_display_h, 2)

    shadow_offset = round(scene_h * 0.012, 2)
    shadow_blur = round(scene_h * 0.025, 2)

    # Build the mockup SVG scene
    mockup_lines = []
    mockup_lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    mockup_lines.append(
        f'<svg xmlns="http://www.w3.org/2000/svg"'
        f' xmlns:xlink="http://www.w3.org/1999/xlink"'
        f' width="{output_width}" height="{output_height}"'
        f' viewBox="0 0 {scene_w} {scene_h}">'
    )

    # Defs: shadow filter + wall texture pattern
    mockup_lines.append("  <defs>")

    # Drop shadow filter
    mockup_lines.append(
        f'    <filter id="frame_shadow" x="-20%" y="-20%" width="140%" height="140%">'
        f'      <feDropShadow dx="{shadow_offset}" dy="{shadow_offset}"'
        f' stdDeviation="{shadow_blur}"'
        f' flood-color="#000000" flood-opacity="{style["shadow_opacity"]}"/>'
        f'    </filter>'
    )

    # Subtle wall texture gradient (top-to-bottom lighting)
    mockup_lines.append(
        f'    <linearGradient id="wall_grad" x1="0" y1="0" x2="0" y2="1">'
        f'      <stop offset="0%" stop-color="{style["wall_color"]}" />'
        f'      <stop offset="60%" stop-color="{style["wall_texture_color"]}" />'
        f'      <stop offset="100%" stop-color="{style["wall_color"]}" />'
        f'    </linearGradient>'
    )

    # Frame bevel gradient (gives the frame 3D depth)
    mockup_lines.append(
        f'    <linearGradient id="frame_bevel" x1="0" y1="0" x2="0" y2="1">'
        f'      <stop offset="0%" stop-color="{style["frame_color"]}" />'
        f'      <stop offset="50%" stop-color="{_lighten_color(style["frame_color"], 0.15)}" />'
        f'      <stop offset="100%" stop-color="{style["frame_color"]}" />'
        f'    </linearGradient>'
    )

    mockup_lines.append("  </defs>")

    # Layer 1: Wall background
    mockup_lines.append(
        f'  <rect width="{scene_w}" height="{scene_h}" fill="url(#wall_grad)"/>'
    )

    # Subtle wall grain lines
    mockup_lines.append('  <g opacity="0.04">')
    grain_spacing = 12
    for gx in range(0, int(scene_w), grain_spacing):
        mockup_lines.append(
            f'    <line x1="{gx}" y1="0" x2="{gx}" y2="{scene_h}"'
            f' stroke="#000000" stroke-width="0.3"/>'
        )
    mockup_lines.append("  </g>")

    # Layer 2: Frame with shadow
    mockup_lines.append(
        f'  <rect x="{frame_x}" y="{frame_y}"'
        f' width="{round(total_w, 2)}" height="{round(total_h, 2)}"'
        f' fill="url(#frame_bevel)" rx="1" ry="1"'
        f' filter="url(#frame_shadow)"/>'
    )

    # Frame inner bevel highlight (top/left edge catch light)
    mockup_lines.append(
        f'  <rect x="{round(frame_x + 1, 2)}" y="{round(frame_y + 1, 2)}"'
        f' width="{round(total_w - 2, 2)}" height="{round(total_h - 2, 2)}"'
        f' fill="none" stroke="{_lighten_color(style["frame_color"], 0.3)}"'
        f' stroke-width="0.5" rx="0.5" opacity="0.4"/>'
    )

    # Layer 3: White mat inside frame
    mockup_lines.append(
        f'  <rect x="{mat_x}" y="{mat_y}"'
        f' width="{mat_inner_w}" height="{mat_inner_h}"'
        f' fill="{style["mat_color"]}"/>'
    )

    # Mat inner shadow (subtle inset shadow where mat meets poster)
    mockup_lines.append(
        f'  <rect x="{poster_x}" y="{poster_y}"'
        f' width="{poster_render_w}" height="{poster_render_h}"'
        f' fill="none" stroke="#00000010" stroke-width="1"/>'
    )

    # Layer 4: The actual map poster, embedded via foreignObject
    # We use an SVG-in-SVG approach: nest the poster SVG directly
    # Extract the inner content of the poster SVG (everything between <svg> and </svg>)
    poster_inner = _extract_svg_inner(clean_svg, poster_w, poster_h)

    mockup_lines.append(
        f'  <svg x="{poster_x}" y="{poster_y}"'
        f' width="{poster_render_w}" height="{poster_render_h}"'
        f' viewBox="0 0 {poster_w} {poster_h}">'
    )
    mockup_lines.append(poster_inner)
    mockup_lines.append("  </svg>")

    # Layer 5: Glass reflection (subtle diagonal highlight)
    mockup_lines.append(
        f'  <rect x="{poster_x}" y="{poster_y}"'
        f' width="{poster_render_w}" height="{poster_render_h}"'
        f' fill="url(#glass_reflect)" opacity="0.06"/>'
    )
    # Add glass reflection gradient to defs (insert before closing)
    # Actually, add it inline
    mockup_lines.append("  <defs>")
    mockup_lines.append(
        f'    <linearGradient id="glass_reflect" x1="0" y1="0" x2="1" y2="1">'
        f'      <stop offset="0%" stop-color="#ffffff" stop-opacity="1"/>'
        f'      <stop offset="40%" stop-color="#ffffff" stop-opacity="0"/>'
        f'      <stop offset="100%" stop-color="#ffffff" stop-opacity="0"/>'
        f'    </linearGradient>'
    )
    mockup_lines.append("  </defs>")

    mockup_lines.append("</svg>")

    mockup_svg = "\n".join(mockup_lines)

    png_bytes = cairosvg.svg2png(
        bytestring=mockup_svg.encode("utf-8"),
        output_width=output_width,
        output_height=output_height,
    )
    return png_bytes


def _extract_svg_inner(svg_string: str, vb_w: float, vb_h: float) -> str:
    """Extract the inner content of an SVG (everything after the opening tag).

    Strips the <?xml?> declaration, opening <svg> tag, and closing </svg> tag,
    returning just the inner elements that can be nested in another SVG.
    """
    # Find the end of the opening <svg ...> tag
    svg_start = svg_string.find("<svg")
    if svg_start == -1:
        return svg_string

    open_end = svg_string.find(">", svg_start)
    if open_end == -1:
        return svg_string

    # Find closing </svg>
    close_start = svg_string.rfind("</svg>")
    if close_start == -1:
        return svg_string[open_end + 1:]

    return svg_string[open_end + 1:close_start]


def _lighten_color(hex_color: str, factor: float) -> str:
    """Lighten a hex color by a factor (0.0 = no change, 1.0 = white)."""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) != 6:
        return f"#{hex_color}"

    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)

    r = min(255, int(r + (255 - r) * factor))
    g = min(255, int(g + (255 - g) * factor))
    b = min(255, int(b + (255 - b) * factor))

    return f"#{r:02x}{g:02x}{b:02x}"
