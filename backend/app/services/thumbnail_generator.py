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

# Color themes for print-ready wall art maps
# Each theme maps CNC SVG colors to print-friendly colors
COLOR_THEMES = {
    "classic": {
        "label": "Classic",
        "background": "#faf8f5",
        "colors": PRINT_COLOR_MAP,
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
    background_color: str = "#f5f0e8",
) -> bytes:
    """Render SVG to a PNG thumbnail image for product listings.

    Args:
        svg_string: The SVG content to render.
        output_width: Pixel width of the output PNG (height scales proportionally).
        background_color: CSS color for the background (warm wood tone by default).

    Returns:
        PNG image as bytes.
    """
    styled_svg = _add_background(svg_string, background_color)

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
) -> bytes:
    """Render SVG to a high-resolution print-ready PNG for wall art.

    Remaps CNC toolpath colors to rich, natural tones suitable for
    professional printing at 300 DPI. Default 4800px width gives
    300 DPI at 16" wide — standard for print shops.

    Args:
        svg_string: The SVG content to render.
        output_width: Pixel width (4800 = 300 DPI at 16"). Use 6000 for 20".
        background_color: Background color override. If None, uses theme default.
        color_theme: Color theme name (classic, modern_dark, rose_gold, etc.).

    Returns:
        High-resolution PNG image as bytes.
    """
    colors = get_theme_colors(color_theme)
    bg = background_color or get_theme_background(color_theme)

    # Remap CNC colors to print-friendly colors
    print_svg = _remap_colors(svg_string, colors)

    # Add background
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
