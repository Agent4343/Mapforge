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
    background_color: str = "#faf8f5",
) -> bytes:
    """Render SVG to a high-resolution print-ready PNG for wall art.

    Remaps CNC toolpath colors to rich, natural tones suitable for
    professional printing at 300 DPI. Default 4800px width gives
    300 DPI at 16" wide — standard for print shops.

    Args:
        svg_string: The SVG content to render.
        output_width: Pixel width (4800 = 300 DPI at 16"). Use 6000 for 20".
        background_color: Background color (warm off-white for print).

    Returns:
        High-resolution PNG image as bytes.
    """
    # Remap CNC colors to print-friendly colors
    print_svg = _remap_colors(svg_string, PRINT_COLOR_MAP)

    # Add background
    print_svg = _add_background(print_svg, background_color)

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
