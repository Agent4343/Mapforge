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
from PIL import Image, ImageDraw, ImageFont

from app.config import settings
from app.logging_config import log


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

    # MapTiler static endpoint has practical image-size limits; fetch at capped
    # size, then upscale for print resolution.
    fetch_scale = min(1.0, 2048.0 / float(max(out_w, 1)), 2048.0 / float(max(map_h, 1)))
    fetch_w = max(512, int(out_w * fetch_scale))
    fetch_h = max(512, int(map_h * fetch_scale))

    style = (style_id or settings.MAPTILER_STYLE_ID or "streets-v2").strip()
    static_url = (
        f"https://api.maptiler.com/maps/{style}/static/"
        f"{lon:.6f},{lat:.6f},{zoom:.2f}/{fetch_w}x{fetch_h}.png?key={key}"
    )

    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.get(static_url)
            resp.raise_for_status()
            map_img = Image.open(io.BytesIO(resp.content)).convert("RGB")
    except Exception as e:
        log.warning(f"MapTiler static render failed: {type(e).__name__}: {e}")
        return None

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

    subtitle = "MapForge"
    sb = draw.textbbox((0, 0), subtitle, font=sub_font)
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

