"""PNG image generator for product mockups and print-ready wall art.

Converts CNC SVG output to PNG images in two modes:
- Thumbnail: 2000px, warm wood background for Etsy/Shopify listings
- Print: 4800px (300 DPI at 16x20"), professional colors for wall art printing

Uses cairosvg for SVG-to-PNG rasterization with color remapping
to transform CNC toolpath colors into rich, natural print colors.
"""

import re

import cairosvg

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
        "background": "#f5f5f0",
        "colors": PRINT_COLOR_MAP,
        "poster": {
            "mat": "#ffffff",
            "map_bg": "#9bbdd6",
            "land": "#ece6d6",
            "land_stroke": "#d4ccb8",
            "water": "#8fb8d8",
            "water_stroke": "#6a9ec4",
            "street_major": "#ffffff",
            "street_minor": "#ffffff",
            "street_label": "#555555",
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
            "land": "#2a2a50",
            "land_stroke": "#3a3c70",
            "water": "#141430",
            "water_stroke": "#3a6ab0",
            "street_major": "#e2e8f0",
            "street_minor": "#a0aec0",
            "street_label": "#cbd5e0",
            "text_primary": "#1a1a2e",
            "text_secondary": "#3a3c70",
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
            "land": "#e8c4bb",
            "land_stroke": "#d4a59a",
            "water": "#a8c8dc",
            "water_stroke": "#7ca8c4",
            "street_major": "#ffffff",
            "street_minor": "#f0d8d0",
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
            "map_bg": "#0a1628",
            "land": "#162a42",
            "land_stroke": "#1e3858",
            "water": "#0c1e38",
            "water_stroke": "#2060a0",
            "street_major": "#c9d6df",
            "street_minor": "#6a8498",
            "street_label": "#a8c4d4",
            "text_primary": "#0f1923",
            "text_secondary": "#244460",
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
            "land": "#a8c4a0",
            "land_stroke": "#7da878",
            "water": "#7db8a8",
            "water_stroke": "#5a9888",
            "street_major": "#ffffff",
            "street_minor": "#d0dcc8",
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
            "map_bg": "#f0f4f8",
            "land": "#e8e8e8",
            "land_stroke": "#cccccc",
            "water": "#6ba3d6",
            "water_stroke": "#4a88bf",
            "street_major": "#222222",
            "street_minor": "#555555",
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
            "water": "#081020",
            "water_stroke": "#1a4080",
            "street_major": "#d4a843",
            "street_minor": "#9a7830",
            "street_label": "#e8c95a",
            "text_primary": "#0a1628",
            "text_secondary": "#1e3560",
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
            "land": "#e8b4b4",
            "land_stroke": "#d49090",
            "water": "#c8a0b0",
            "water_stroke": "#b08098",
            "street_major": "#ffffff",
            "street_minor": "#f0d0d0",
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
            "map_bg": "#b8dce8",
            "land": "#4a9e6e",
            "land_stroke": "#388058",
            "water": "#3498db",
            "water_stroke": "#2080c0",
            "street_major": "#ffffff",
            "street_minor": "#c0e0c8",
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
            "land": "#404040",
            "land_stroke": "#555555",
            "water": "#222222",
            "water_stroke": "#3a3a3a",
            "street_major": "#e0d5c1",
            "street_minor": "#8a7e68",
            "street_label": "#d4c5a9",
            "text_primary": "#2d2d2d",
            "text_secondary": "#4a4a4a",
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
            "land": "#c8a882",
            "land_stroke": "#a08060",
            "water": "#8ab0c8",
            "water_stroke": "#6890a8",
            "street_major": "#ffffff",
            "street_minor": "#e0d0b8",
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
            "land": "#b8a8d0",
            "land_stroke": "#9888b8",
            "water": "#9898c8",
            "water_stroke": "#7878a8",
            "street_major": "#ffffff",
            "street_minor": "#d0c8e0",
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
            "land": "#1a4020",
            "land_stroke": "#2a5830",
            "water": "#0a1810",
            "water_stroke": "#1a3a28",
            "street_major": "#c4b896",
            "street_minor": "#8a7e58",
            "street_label": "#d4c5a0",
            "text_primary": "#0d1f0d",
            "text_secondary": "#1a4a1a",
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
            "land": "#e8a060",
            "land_stroke": "#c88040",
            "water": "#d08858",
            "water_stroke": "#b06840",
            "street_major": "#ffffff",
            "street_minor": "#f0d0b0",
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
            "map_bg": "#d8ecf8",
            "land": "#e0eef5",
            "land_stroke": "#a8c8dc",
            "water": "#5dade2",
            "water_stroke": "#3498db",
            "street_major": "#2c3e50",
            "street_minor": "#5a7a90",
            "street_label": "#1a252f",
            "text_primary": "#1a252f",
            "text_secondary": "#2c3e50",
        },
    },
    "blueprint": {
        "label": "Blueprint",
        "background": "#1a2744",
        "colors": {
            "#2a2a2a": "#1e3050",
            "#1a1a1a": "#e8eef6",
            "#d4e6f1": "#1a2744",
            "#7fb3d3": "#4a7ab5",
            "#333333": "#e8eef6",
            "#555555": "#a0b8d8",
            "#444444": "#c8d8ee",
            "#cccccc": "#2a3d5e",
            "#666666": "#8aa8d0",
        },
        "poster": {
            "mat": "#ffffff",
            "map_bg": "#1a2744",
            "land": "#223458",
            "land_stroke": "#2a4570",
            "water": "#142040",
            "water_stroke": "#3a6098",
            "street_major": "#e8eef6",
            "street_minor": "#7090b8",
            "street_label": "#c8d8ee",
            "text_primary": "#1a2744",
            "text_secondary": "#2a4570",
        },
    },
    "dark": {
        "label": "Dark",
        "background": "#0a0a0a",
        "colors": {
            "#2a2a2a": "#1a1a1a",
            "#1a1a1a": "#d0d0d0",
            "#d4e6f1": "#151515",
            "#7fb3d3": "#333333",
            "#333333": "#cccccc",
            "#555555": "#888888",
            "#444444": "#aaaaaa",
            "#cccccc": "#1a1a1a",
            "#666666": "#999999",
        },
        "poster": {
            "mat": "#ffffff",
            "map_bg": "#0a0a0a",
            "land": "#1a1a1a",
            "land_stroke": "#2a2a2a",
            "water": "#050505",
            "water_stroke": "#1a1a1a",
            "street_major": "#d0d0d0",
            "street_minor": "#666666",
            "street_label": "#aaaaaa",
            "text_primary": "#0a0a0a",
            "text_secondary": "#333333",
        },
    },
    "engraving": {
        "label": "Engraving",
        "background": "#f8f5ef",
        "colors": {
            "#2a2a2a": "#f0ebe0",
            "#1a1a1a": "#2a2520",
            "#d4e6f1": "#e8e0d4",
            "#7fb3d3": "#8a7e6e",
            "#333333": "#2a2520",
            "#555555": "#5a5048",
            "#444444": "#1a1510",
            "#cccccc": "#d8d0c4",
            "#666666": "#4a4038",
        },
        "poster": {
            "mat": "#ffffff",
            "map_bg": "#f8f5ef",
            "land": "#e8e0d0",
            "land_stroke": "#c0b098",
            "water": "#d0c8b8",
            "water_stroke": "#a89880",
            "street_major": "#2a2520",
            "street_minor": "#5a5048",
            "street_label": "#1a1510",
            "text_primary": "#1a1510",
            "text_secondary": "#5a5048",
        },
    },
}


def build_custom_theme(bg: str, land: str, water: str, road: str, text: str) -> dict:
    """Build a custom theme from user-specified hex colors."""
    # Derive secondary colors from the primary ones
    return {
        "label": "Custom",
        "background": bg,
        "colors": PRINT_COLOR_MAP,
        "poster": {
            "mat": "#ffffff",
            "map_bg": bg,
            "land": land,
            "land_stroke": _darken(land, 0.2),
            "water": water,
            "water_stroke": _darken(water, 0.25),
            "street_major": road,
            "street_minor": _lighten(road, 0.3),
            "street_label": road,
            "text_primary": text,
            "text_secondary": _lighten(text, 0.3),
        },
    }


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Convert hex color to RGB tuple."""
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    """Convert RGB to hex color."""
    return f"#{max(0,min(255,r)):02x}{max(0,min(255,g)):02x}{max(0,min(255,b)):02x}"


def _darken(hex_color: str, factor: float) -> str:
    """Darken a hex color by a factor (0-1)."""
    r, g, b = _hex_to_rgb(hex_color)
    return _rgb_to_hex(int(r * (1 - factor)), int(g * (1 - factor)), int(b * (1 - factor)))


def _lighten(hex_color: str, factor: float) -> str:
    """Lighten a hex color by a factor (0-1)."""
    r, g, b = _hex_to_rgb(hex_color)
    return _rgb_to_hex(
        int(r + (255 - r) * factor),
        int(g + (255 - g) * factor),
        int(b + (255 - b) * factor),
    )


def get_theme_colors(theme_name: str) -> dict:
    """Get color map for a theme. Falls back to classic."""
    theme = COLOR_THEMES.get(theme_name, COLOR_THEMES["classic"])
    return theme["colors"]


def get_theme_background(theme_name: str) -> str:
    """Get background color for a theme."""
    theme = COLOR_THEMES.get(theme_name, COLOR_THEMES["classic"])
    return theme["background"]


def get_poster_theme(theme_name: str, custom_colors: dict | None = None) -> dict:
    """Get poster-specific color palette for print-mode SVG generation.

    If theme_name is "custom" and custom_colors is provided, builds a
    custom theme from the user's hex color choices.
    """
    if theme_name == "custom" and custom_colors:
        custom = build_custom_theme(
            bg=custom_colors.get("bg", "#ffffff"),
            land=custom_colors.get("land", "#e0e0e0"),
            water=custom_colors.get("water", "#a0c0e0"),
            road=custom_colors.get("road", "#333333"),
            text=custom_colors.get("text", "#1a1a1a"),
        )
        return custom["poster"]
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
    styled_svg = _add_background(svg_string, background_color) if background_color else svg_string

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
