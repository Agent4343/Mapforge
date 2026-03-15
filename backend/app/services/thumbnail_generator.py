"""PNG thumbnail generator for Etsy product mockups.

Converts CNC SVG output to a high-quality PNG image suitable for
product listings on Etsy, Shopify, or social media.

Uses cairosvg for SVG-to-PNG rasterization with configurable
output dimensions and background colors.
"""

import cairosvg


def generate_thumbnail(
    svg_string: str,
    output_width: int = 2000,
    background_color: str = "#f5f0e8",
) -> bytes:
    """Render SVG to a PNG thumbnail image.

    Args:
        svg_string: The SVG content to render.
        output_width: Pixel width of the output PNG (height scales proportionally).
        background_color: CSS color for the background (warm wood tone by default).

    Returns:
        PNG image as bytes.
    """
    # Inject a background rect if the SVG doesn't have one.
    # This gives the thumbnail a warm "wood board" look for Etsy listings.
    styled_svg = _add_background(svg_string, background_color)

    png_bytes = cairosvg.svg2png(
        bytestring=styled_svg.encode("utf-8"),
        output_width=output_width,
    )
    return png_bytes


def _add_background(svg_string: str, color: str) -> str:
    """Insert a background rectangle right after the opening <svg> tag."""
    # Find the end of the opening <svg ...> tag
    svg_open_end = svg_string.find(">")
    if svg_open_end == -1:
        return svg_string

    # Skip past XML declaration if present
    start = svg_string.find("<svg")
    if start == -1:
        return svg_string
    svg_open_end = svg_string.find(">", start)

    # Extract viewBox dimensions for the background rect
    vb_width, vb_height = _parse_viewbox(svg_string)

    bg_rect = (
        f'\n  <rect width="{vb_width}" height="{vb_height}"'
        f' fill="{color}" />'
    )

    return svg_string[: svg_open_end + 1] + bg_rect + svg_string[svg_open_end + 1 :]


def _parse_viewbox(svg_string: str) -> tuple[str, str]:
    """Extract width and height from the viewBox attribute."""
    import re

    match = re.search(r'viewBox="([^"]+)"', svg_string)
    if match:
        parts = match.group(1).split()
        if len(parts) == 4:
            return parts[2], parts[3]

    # Fallback: try width/height attributes
    w_match = re.search(r'width="([0-9.]+)', svg_string)
    h_match = re.search(r'height="([0-9.]+)', svg_string)
    w = w_match.group(1) if w_match else "100%"
    h = h_match.group(1) if h_match else "100%"
    return w, h
