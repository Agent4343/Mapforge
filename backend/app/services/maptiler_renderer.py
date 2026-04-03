"""MapTiler-backed raster export helpers for print pipeline.

This renderer fetches static map tiles from MapTiler and composites the final
poster PNG/PDF with typography, giving a direct MapTiler-based print path.
"""

from __future__ import annotations

import io
import math
import re
from typing import Any

import httpx
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from app.config import settings
from app.logging_config import log

_CITY_ART_PRODUCT_TYPES = {"city", "community", "name_sign"}


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Best-effort font loader with robust fallbacks."""
    candidates = []
    if bold:
        candidates.extend(
            [
                "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            ]
        )
    candidates.extend(
        [
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
    )
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except Exception:
            continue
    return ImageFont.load_default()


def _title_from_svg(svg: str) -> str:
    up = svg.upper()
    marker = 'id="poster_text"'
    idx = up.find(marker.upper())
    if idx == -1:
        return "MAPFORGE"
    snippet = svg[idx : idx + 1500]
    t_start = snippet.find(">")
    if t_start == -1:
        return "MAPFORGE"
    # first visible text node in poster_text group
    for line in snippet.splitlines():
        if "<text" in line and "</text>" in line:
            a = line.find(">")
            b = line.rfind("</text>")
            if a != -1 and b != -1 and b > a:
                text = line[a + 1 : b].strip()
                if text:
                    return text
    return "MAPFORGE"


def _extract_poster_subtitle(svg: str) -> str:
    """Extract subtitle text from poster_text group if present."""
    marker = 'id="poster_text"'
    idx = svg.find(marker)
    if idx == -1:
        return ""
    snippet = svg[idx : idx + 2200]
    texts: list[str] = []
    for line in snippet.splitlines():
        if "<text" in line and "</text>" in line:
            a = line.find(">")
            b = line.rfind("</text>")
            if a != -1 and b != -1 and b > a:
                t = line[a + 1 : b].strip()
                if t:
                    texts.append(t)
    # Typical order: title, subtitle, coordinates.
    if len(texts) >= 3:
        return texts[1]
    return ""


def _extract_viewbox(svg: str) -> tuple[float, float]:
    marker = 'viewBox="'
    i = svg.find(marker)
    if i == -1:
        return (406.4, 508.0)
    j = svg.find('"', i + len(marker))
    if j == -1:
        return (406.4, 508.0)
    values = svg[i + len(marker) : j].split()
    if len(values) != 4:
        return (406.4, 508.0)
    try:
        return (float(values[2]), float(values[3]))
    except Exception:
        return (406.4, 508.0)


def _extract_center_latlon(svg: str) -> tuple[float, float] | None:
    # Reads coordinate line: 46.1464°N  •  60.1819°W
    marker = "°N"
    idx = svg.find(marker)
    if idx == -1:
        marker = "°S"
        idx = svg.find(marker)
        if idx == -1:
            return None
    line_start = max(0, svg.rfind("\n", 0, idx))
    line_end = svg.find("\n", idx)
    if line_end == -1:
        line_end = len(svg)
    line = svg[line_start:line_end]
    try:
        # permissive parse for patterns like:
        # 46.1464°N  •  60.1819°W
        # 46.1464° N 60.1819° W
        normalized = (
            line.replace("•", " ")
            .replace("&nbsp;", " ")
            .replace("</text>", " ")
            .replace("<text>", " ")
        )
        pattern = r"([0-9]+(?:\.[0-9]+)?)\s*°\s*([NSEW])"
        matches = re.findall(pattern, normalized)
        if len(matches) >= 2:
            lat_v, lat_d = float(matches[0][0]), matches[0][1]
            lon_v, lon_d = float(matches[1][0]), matches[1][1]
            lat = lat_v * (-1 if lat_d == "S" else 1)
            lon = lon_v * (-1 if lon_d == "W" else 1)
            return (lat, lon)
    except Exception:
        return None
    return None


async def _resolve_maptiler_key(db: Any | None = None, maptiler_key: str | None = None) -> str:
    if maptiler_key and maptiler_key.strip():
        return maptiler_key.strip()
    key = (settings.MAPTILER_KEY or "").strip()
    if not db:
        return key
    try:
        from app.services.app_settings import get_maptiler_key
        key = (await get_maptiler_key(db) or key or "").strip()
    except Exception as e:
        log.warning(f"MapTiler key lookup failed in renderer: {e}")
    return key


async def _resolve_style_id(db: Any | None = None, style_id: str | None = None) -> str:
    """Resolve MapTiler static style with an art-focused default."""
    # Explicit style_id always wins.
    if style_id and style_id.strip():
        return style_id.strip()

    resolved = (settings.MAPTILER_STATIC_STYLE or "").strip()
    if db is not None:
        try:
            from app.services.app_settings import get_maptiler_static_style

            resolved = (await get_maptiler_static_style(db) or resolved or "").strip()
        except Exception as e:
            log.warning(f"MapTiler style lookup failed in renderer: {e}")

    # Legacy default `streets-v2` reads as navigation UI, not printable wall art.
    if not resolved or resolved.lower() == "streets-v2":
        return "backdrop"
    return resolved


def _lat_to_mercator_rad(lat: float) -> float:
    sin = math.sin(lat * math.pi / 180.0)
    rad_x2 = math.log((1 + sin) / (1 - sin)) / 2
    return max(min(rad_x2, math.pi), -math.pi) / 2


def _zoom_to_fit_bbox(
    min_lat: float,
    min_lon: float,
    max_lat: float,
    max_lon: float,
    width_px: int,
    height_px: int,
) -> float:
    """Estimate WebMercator zoom that fits bbox into width/height pixels."""
    if width_px <= 0 or height_px <= 0:
        return 12.0

    lon_delta = max(0.00001, abs(max_lon - min_lon))
    lat_fraction = abs(_lat_to_mercator_rad(max_lat) - _lat_to_mercator_rad(min_lat)) / math.pi
    lon_fraction = lon_delta / 360.0

    zoom_lon = math.log2(width_px / 256.0 / lon_fraction) if lon_fraction > 0 else 20
    zoom_lat = math.log2(height_px / 256.0 / max(lat_fraction, 0.00001))
    zoom = min(zoom_lon, zoom_lat) - 0.35  # slight breathing room
    return max(4.0, min(15.5, zoom))


def _apply_product_zoom_bias(zoom: float, product_type: str | None) -> float:
    """Nudge zoom by product type for better visual composition."""
    pt = (product_type or "").strip().lower()
    # Regions need to zoom out slightly; city/name_sign can zoom in.
    bias = {
        "province": -0.8,
        "park": -0.45,
        "lake": -0.25,
        "community": 0.15,
        "city": 0.35,
        "name_sign": 0.55,
    }.get(pt, 0.0)
    return max(4.0, min(15.5, zoom + bias))


def _normalize_style_id(style_id: str | None) -> str:
    """Sanitize style id and default to art-oriented style."""
    style = (style_id or "").strip().lower()
    if not style:
        return "backdrop"
    if style == "streets-v2":
        return "backdrop"
    if style.startswith("http://") or style.startswith("https://"):
        return "backdrop"
    if style.startswith("{") or style.endswith(".json"):
        return "backdrop"
    return style


def _stylize_map_for_print_art(map_img: Image.Image, product_type: str | None) -> Image.Image:
    """Convert city-scale map tiles into cleaner monochrome poster linework."""
    pt = (product_type or "").strip().lower()
    if pt not in {"city", "community", "name_sign"}:
        return map_img

    gray = map_img.convert("L").filter(ImageFilter.GaussianBlur(0.9))

    # Edge-first extraction avoids giant dark fill blocks from water/land polygons.
    edges = gray.filter(ImageFilter.FIND_EDGES)
    minor_mask = edges.point(lambda p: 255 if p > 26 else 0, mode="L")
    major_mask = edges.point(lambda p: 255 if p > 46 else 0, mode="L")

    # Keep coherent linework while dropping isolated noise.
    minor_mask = minor_mask.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3))
    major_mask = major_mask.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3))
    major_mask = major_mask.filter(ImageFilter.MaxFilter(3))

    # Recover dark linear features while suppressing thick region interiors.
    dark_seed = gray.point(lambda p: 255 if p < 138 else 0, mode="L")
    dark_core = dark_seed.filter(ImageFilter.MinFilter(7))
    dark_edges = ImageChops.subtract(dark_seed, dark_core).filter(ImageFilter.MaxFilter(3))
    minor_mask = ImageChops.lighter(minor_mask, dark_edges)

    # Strong line layer from darkest structures, with region interiors removed.
    major_seed = gray.point(lambda p: 255 if p < 106 else 0, mode="L")
    major_core = major_seed.filter(ImageFilter.MinFilter(5))
    major_edges = ImageChops.subtract(major_seed, major_core).filter(ImageFilter.MaxFilter(3))
    major_mask = ImageChops.lighter(major_mask, major_edges)

    art = Image.new("RGB", map_img.size, color="#efefed")
    minor_layer = Image.new("RGB", map_img.size, color="#b8b8b8")
    major_layer = Image.new("RGB", map_img.size, color="#3f3f3f")
    art.paste(minor_layer, mask=minor_mask)
    art.paste(major_layer, mask=major_mask)
    return art


def _pick_art_style(style: str, product_type: str | None) -> str:
    """Choose art-friendly style variants by product type."""
    # Keep configured style exactly as selected by admin/user.
    # No implicit switching by product type.
    return style


def _line_ink_ratio(map_img: Image.Image) -> float:
    """Estimate visible line density to catch near-blank map outputs."""
    sample = map_img.convert("L").resize((220, 220), Image.Resampling.BILINEAR)
    px = sample.tobytes()
    total = len(px) or 1
    # "Ink" means visibly dark linework, not off-white paper/background.
    ink = sum(1 for v in px if v < 185)
    return float(ink) / float(total)


def _should_recover_from_blank_art(raw_img: Image.Image, styled_img: Image.Image, product_type: str | None) -> bool:
    """Detect aggressive post-processing that erased most visible linework."""
    if (product_type or "").strip().lower() not in _CITY_ART_PRODUCT_TYPES:
        return False
    raw_ratio = _line_ink_ratio(raw_img)
    styled_ratio = _line_ink_ratio(styled_img)
    # Very sparse styled result plus large drop from the source tile means the
    # art transform was too aggressive for this viewport/style.
    return styled_ratio < 0.0022 and raw_ratio > max(styled_ratio * 2.0, 0.006)


async def _fetch_static_map_image(
    *,
    style: str,
    lon: float,
    lat: float,
    zoom: float,
    width: int,
    height: int,
    key: str,
) -> Image.Image | None:
    static_url = (
        f"https://api.maptiler.com/maps/{style}/static/"
        f"{lon:.6f},{lat:.6f},{zoom:.2f}/{width}x{height}.png?key={key}"
    )
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.get(static_url)
            resp.raise_for_status()
            return Image.open(io.BytesIO(resp.content)).convert("RGB")
    except Exception as e:
        log.warning(f"MapTiler static render failed ({style}): {type(e).__name__}: {e}")
        return None


async def render_maptiler_print_png(
    *,
    svg: str,
    board_size: str,
    dpi: int,
    db: Any | None = None,
    maptiler_key: str | None = None,
    style_id: str | None = None,
    title_override: str | None = None,
    center_latlon: tuple[float, float] | None = None,
    bounds_latlon: tuple[float, float, float, float] | None = None,
    product_type: str | None = None,
    max_output_dimension: int | None = None,
) -> bytes | None:
    """Render print-ready PNG via MapTiler static endpoint.

    Returns None if key/coords are unavailable or fetch fails.
    """
    key = await _resolve_maptiler_key(db, maptiler_key=maptiler_key)
    if not key:
        return None

    center = center_latlon or _extract_center_latlon(svg)
    if not center:
        return None
    lat, lon = center

    # Determine target print pixels from board_size+dpi.
    from app.services.thumbnail_generator import PRINT_DPI_STANDARD, PRINT_SIZE_PIXELS

    base = PRINT_SIZE_PIXELS.get(board_size)
    if not base:
        return None
    scale = dpi / PRINT_DPI_STANDARD
    out_w = int(base[0] * scale)
    out_h = int(base[1] * scale)
    if max_output_dimension and max_output_dimension > 0:
        downscale = min(
            1.0,
            float(max_output_dimension) / float(max(out_w, 1)),
            float(max_output_dimension) / float(max(out_h, 1)),
        )
        out_w = max(512, int(out_w * downscale))
        out_h = max(640, int(out_h * downscale))

    # Reserve bottom typography band similar to vintage layout.
    text_band_h = max(220, int(out_h * 0.14))
    map_h = out_h - text_band_h

    # Use fit-to-bounds zoom when available; otherwise conservative default.
    if bounds_latlon:
        zoom = _zoom_to_fit_bbox(
            min_lat=bounds_latlon[0],
            min_lon=bounds_latlon[1],
            max_lat=bounds_latlon[2],
            max_lon=bounds_latlon[3],
            width_px=out_w,
            height_px=map_h,
        )
    else:
        zoom = 12.2
        if board_size in {"print_24x36", "print_18x24"}:
            zoom = 11.7
        elif board_size in {"print_8x10", "print_11x14"}:
            zoom = 12.6
    zoom = _apply_product_zoom_bias(zoom, product_type)

    # MapTiler static endpoint has practical image-size limits; fetch at capped
    # size, then upscale for print resolution.
    fetch_scale = min(1.0, 2048.0 / float(max(out_w, 1)), 2048.0 / float(max(map_h, 1)))
    fetch_w = max(512, int(out_w * fetch_scale))
    fetch_h = max(512, int(map_h * fetch_scale))

    style = _normalize_style_id(await _resolve_style_id(db, style_id=style_id))
    style = _pick_art_style(style, product_type)
    map_img = await _fetch_static_map_image(
        style=style,
        lon=lon,
        lat=lat,
        zoom=zoom,
        width=fetch_w,
        height=fetch_h,
        key=key,
    )
    if map_img is None:
        return None

    raw_map_img = map_img
    map_img = _stylize_map_for_print_art(raw_map_img, product_type)
    if _should_recover_from_blank_art(raw_map_img, map_img, product_type):
        fallback_style = "toner-v2" if style != "toner-v2" else "basic-v2"
        alt_raw = await _fetch_static_map_image(
            style=fallback_style,
            lon=lon,
            lat=lat,
            zoom=zoom,
            width=fetch_w,
            height=fetch_h,
            key=key,
        )
        if alt_raw is not None:
            alt_styled = _stylize_map_for_print_art(alt_raw, product_type)
            map_img = alt_styled if _line_ink_ratio(alt_styled) > _line_ink_ratio(map_img) else alt_raw
            log.info(f"Recovered sparse map art using fallback style: {fallback_style}")
        else:
            map_img = raw_map_img
            log.info("Recovered sparse map art by reverting to raw static tile image")

    poster = Image.new("RGB", (out_w, out_h), color="#f6f0e4")
    poster.paste(map_img.resize((out_w, map_h), Image.Resampling.LANCZOS), (0, 0))

    draw = ImageDraw.Draw(poster)
    title = (title_override or _title_from_svg(svg) or "MAPFORGE").strip()
    title_font = _load_font(max(36, int(out_h * 0.03)), bold=True)
    sub_font = _load_font(max(20, int(out_h * 0.015)))
    coord_font = _load_font(max(18, int(out_h * 0.012)))

    title_bbox = draw.textbbox((0, 0), title, font=title_font)
    title_w = title_bbox[2] - title_bbox[0]
    title_x = (out_w - title_w) // 2
    y0 = map_h + max(28, int(text_band_h * 0.18))
    draw.text((title_x, y0), title, fill="#1f1a14", font=title_font)

    subtitle = _extract_poster_subtitle(svg).strip()
    sb = draw.textbbox((0, 0), subtitle, font=sub_font)
    if subtitle:
        draw.text(((out_w - (sb[2] - sb[0])) // 2, y0 + int((sb[3] - sb[1]) * 1.8)), subtitle, fill="#4f4230", font=sub_font)

    coord_text = f"{abs(lat):.4f}°{'N' if lat >= 0 else 'S'} • {abs(lon):.4f}°{'E' if lon >= 0 else 'W'}"
    cb = draw.textbbox((0, 0), coord_text, font=coord_font)
    draw.text(((out_w - (cb[2] - cb[0])) // 2, y0 + int((sb[3] - sb[1]) * 3.5)), coord_text, fill="#5b4b38", font=coord_font)
    attr_text = "© MapTiler © OpenStreetMap contributors"
    ab = draw.textbbox((0, 0), attr_text, font=coord_font)
    draw.text(
        ((out_w - (ab[2] - ab[0])) // 2, out_h - max(24, int(out_h * 0.022))),
        attr_text,
        fill="#6a5a46",
        font=coord_font,
    )

    # simple dual border for gallery look
    m1 = max(6, int(out_w * 0.006))
    m2 = m1 + max(6, int(out_w * 0.004))
    draw.rectangle([m1, m1, out_w - m1, out_h - m1], outline="#3b3024", width=max(1, int(out_w * 0.001)))
    draw.rectangle([m2, m2, out_w - m2, out_h - m2], outline="#5a4833", width=1)

    buf = io.BytesIO()
    poster.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def render_png_bytes_to_pdf(png_bytes: bytes) -> bytes:
    """Wrap PNG bytes into a single-page PDF."""
    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    out = io.BytesIO()
    img.save(out, format="PDF", resolution=300.0)
    return out.getvalue()

