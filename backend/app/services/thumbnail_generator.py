"""PNG image generator for product mockups and print-ready wall art.

Converts CNC SVG output to PNG images in two modes:
- Thumbnail: 2000px, warm wood background for Etsy/Shopify listings
- Print: 4800px (300 DPI at 16x20"), professional colors for wall art printing

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
            "map_bg": "#f5f0e8",
            "land": "#e8dfd0",
            "land_stroke": "#c4b598",
            "water": "#a3cceb",
            "water_stroke": "#5a9fd4",
            "street_major": "#333333",
            "street_minor": "#666666",
            "street_label": "#333333",
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
            "map_bg": "#1a1a2e",
            "land": "#22244a",
            "land_stroke": "#3a3c70",
            "water": "#1a3a6a",
            "water_stroke": "#3a6ab0",
            "street_major": "#e2e8f0",
            "street_minor": "#a0aec0",
            "street_label": "#cbd5e0",
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
            "land": "#f5e0db",
            "land_stroke": "#d4a59a",
            "water": "#c8dce8",
            "water_stroke": "#9abdd4",
            "street_major": "#8b6f66",
            "street_minor": "#b8a098",
            "street_label": "#6b5550",
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
            "map_bg": "#0f1923",
            "land": "#182d40",
            "land_stroke": "#244460",
            "water": "#0c2845",
            "water_stroke": "#2560a0",
            "street_major": "#c9d6df",
            "street_minor": "#8fa7b8",
            "street_label": "#a8c4d4",
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
            "map_bg": "#eef2ea",
            "land": "#dfe8d8",
            "land_stroke": "#b8c8ac",
            "water": "#c0d8d0",
            "water_stroke": "#8bb8a8",
            "street_major": "#4a5e44",
            "street_minor": "#7d9b76",
            "street_label": "#3d4e38",
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
            "map_bg": "#ffffff",
            "land": "#ffffff",
            "land_stroke": "#e0e0e0",
            "water": "#f0f0f0",
            "water_stroke": "#cccccc",
            "street_major": "#222222",
            "street_minor": "#666666",
            "street_label": "#444444",
            "text_primary": "#111111",
            "text_secondary": "#666666",
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
            "map_bg": "#0a1628",
            "land": "#122240",
            "land_stroke": "#1e3560",
            "water": "#0a2050",
            "water_stroke": "#1a4080",
            "street_major": "#d4a843",
            "street_minor": "#b8943a",
            "street_label": "#e8c95a",
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
            "land": "#f8e0e0",
            "land_stroke": "#e8b4b4",
            "water": "#e8d0d8",
            "water_stroke": "#d4a0b0",
            "street_major": "#8b5e5e",
            "street_minor": "#c27c7c",
            "street_label": "#6b4545",
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
            "land": "#d0e8f0",
            "land_stroke": "#90c0d8",
            "water": "#a8d4e8",
            "water_stroke": "#5dade2",
            "street_major": "#1a5276",
            "street_minor": "#2980b9",
            "street_label": "#0e3d5c",
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
            "map_bg": "#2d2d2d",
            "land": "#383838",
            "land_stroke": "#4a4a4a",
            "water": "#262626",
            "water_stroke": "#404040",
            "street_major": "#e0d5c1",
            "street_minor": "#b8a88a",
            "street_label": "#d4c5a9",
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
            "land": "#eddcc8",
            "land_stroke": "#d4b896",
            "water": "#c8d8e0",
            "water_stroke": "#90b0c0",
            "street_major": "#8b4513",
            "street_minor": "#a0522d",
            "street_label": "#6b3410",
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
            "land": "#e4dff0",
            "land_stroke": "#c0b4d8",
            "water": "#d0cae8",
            "water_stroke": "#a898c8",
            "street_major": "#5b4a8a",
            "street_minor": "#7b6ba0",
            "street_label": "#3d2e6b",
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
            "map_bg": "#0d1f0d",
            "land": "#142814",
            "land_stroke": "#1a4a1a",
            "water": "#0a180a",
            "water_stroke": "#1a3a1a",
            "street_major": "#c4b896",
            "street_minor": "#a0956b",
            "street_label": "#d4c5a0",
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
            "land": "#f8e8d0",
            "land_stroke": "#e8c8a0",
            "water": "#e8d8c8",
            "water_stroke": "#d4b898",
            "street_major": "#c0392b",
            "street_minor": "#d35400",
            "street_label": "#922b21",
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
            "map_bg": "#eef5fb",
            "land": "#e0eef5",
            "land_stroke": "#b0d0e4",
            "water": "#c8e0f0",
            "water_stroke": "#85c1e9",
            "street_major": "#2c3e50",
            "street_minor": "#34495e",
            "street_label": "#1a252f",
            "text_primary": "#1a252f",
            "text_secondary": "#2c3e50",
        },
    },
}


def get_theme_colors(theme_name: str) -> dict:
    """Get color map for a theme. Falls back to classic."""
    theme = COLOR_THEMES.get(theme_name, COLOR_THEMES["classic"])
    return theme["colors"]


def get_theme_background(theme_name: str) -> str:
    """Get background color for a theme."""
    theme = COLOR_THEMES.get(theme_name, COLOR_THEMES["classic"])
    return theme["background"]


def get_poster_theme(theme_name: str) -> dict:
    """Get poster-specific color palette for print-mode SVG generation."""
    theme = COLOR_THEMES.get(theme_name, COLOR_THEMES["classic"])
    return theme.get("poster", COLOR_THEMES["classic"]["poster"])


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
