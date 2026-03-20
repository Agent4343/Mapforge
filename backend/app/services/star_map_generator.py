"""Star map generator — renders the night sky for a given date, time, and location.

Uses a built-in catalog of the ~300 brightest stars (down to magnitude ~3.5)
plus constellation lines. No external API dependency.

The output is an SVG-compatible list of star positions and constellation lines
projected onto a circular viewport using stereographic projection.
"""

import math
from datetime import datetime, timezone


# Bright Star Catalog — ~150 brightest stars visible to naked eye
# Format: (name, RA_hours, Dec_degrees, magnitude)
# RA in decimal hours, Dec in decimal degrees
BRIGHT_STARS = [
    ("Sirius", 6.752, -16.716, -1.46),
    ("Canopus", 6.399, -52.696, -0.74),
    ("Arcturus", 14.261, 19.182, -0.05),
    ("Vega", 18.616, 38.784, 0.03),
    ("Capella", 5.278, 45.998, 0.08),
    ("Rigel", 5.242, -8.202, 0.13),
    ("Procyon", 7.655, 5.225, 0.34),
    ("Betelgeuse", 5.919, 7.407, 0.42),
    ("Achernar", 1.629, -57.237, 0.46),
    ("Hadar", 14.064, -60.373, 0.61),
    ("Altair", 19.846, 8.868, 0.77),
    ("Acrux", 12.443, -63.100, 0.77),
    ("Aldebaran", 4.599, 16.509, 0.85),
    ("Antares", 16.490, -26.432, 0.96),
    ("Spica", 13.420, -11.161, 0.97),
    ("Pollux", 7.755, 28.026, 1.14),
    ("Fomalhaut", 22.961, -29.622, 1.16),
    ("Deneb", 20.690, 45.280, 1.25),
    ("Mimosa", 12.795, -59.689, 1.25),
    ("Regulus", 10.140, 11.967, 1.35),
    ("Adhara", 6.977, -28.972, 1.50),
    ("Castor", 7.577, 31.888, 1.58),
    ("Gacrux", 12.519, -57.113, 1.63),
    ("Shaula", 17.560, -37.104, 1.63),
    ("Bellatrix", 5.419, 6.350, 1.64),
    ("Elnath", 5.438, 28.608, 1.65),
    ("Miaplacidus", 9.220, -69.717, 1.68),
    ("Alnilam", 5.604, -1.202, 1.69),
    ("Alnair", 22.137, -46.961, 1.74),
    ("Alnitak", 5.679, -1.943, 1.77),
    ("Alioth", 12.900, 55.960, 1.77),
    ("Dubhe", 11.062, 61.751, 1.79),
    ("Mirfak", 3.405, 49.861, 1.80),
    ("Wezen", 7.140, -26.393, 1.84),
    ("Kaus Australis", 18.403, -34.384, 1.85),
    ("Alkaid", 13.792, 49.314, 1.86),
    ("Sargas", 17.622, -42.998, 1.87),
    ("Avior", 8.376, -59.509, 1.86),
    ("Menkalinan", 5.992, 44.948, 1.90),
    ("Atria", 16.811, -69.028, 1.92),
    ("Alhena", 6.629, 16.399, 1.93),
    ("Peacock", 20.428, -56.735, 1.94),
    ("Mirzam", 6.378, -17.956, 1.98),
    ("Alphard", 9.460, -8.659, 1.98),
    ("Polaris", 2.530, 89.264, 2.02),
    ("Hamal", 2.120, 23.462, 2.00),
    ("Diphda", 0.726, -17.987, 2.02),
    ("Mizar", 13.399, 54.925, 2.06),
    ("Nunki", 18.921, -26.297, 2.05),
    ("Saiph", 5.796, -9.670, 2.09),
    ("Alpheratz", 0.140, 29.091, 2.06),
    ("Mintaka", 5.533, -0.299, 2.23),
    ("Merak", 11.031, 56.382, 2.37),
    ("Phecda", 11.897, 53.695, 2.44),
    ("Megrez", 12.257, 57.033, 3.31),
    ("Denebola", 11.818, 14.572, 2.14),
    ("Rasalhague", 17.582, 12.560, 2.07),
    ("Algol", 3.136, 40.956, 2.12),
    ("Schedar", 0.675, 56.537, 2.23),
    ("Caph", 0.153, 59.150, 2.27),
    ("Almach", 2.065, 42.330, 2.17),
    ("Kochab", 14.845, 74.156, 2.08),
    ("Rasalgethi", 17.244, 14.390, 2.81),
    ("Enif", 21.736, 9.875, 2.39),
    ("Markab", 23.079, 15.205, 2.49),
    ("Scheat", 23.063, 28.083, 2.42),
    ("Algenib", 0.220, 15.184, 2.83),
    ("Mirach", 1.163, 35.621, 2.05),
    ("Zubenelgenubi", 14.848, -16.042, 2.75),
    ("Zubeneschamali", 15.283, -9.383, 2.61),
    ("Unukalhai", 15.738, 6.426, 2.65),
    ("Sabik", 17.173, -15.725, 2.43),
    ("Dschubba", 16.005, -22.622, 2.32),
    ("Graffias", 16.091, -19.806, 2.62),
    ("Sargas", 17.622, -42.998, 1.87),
    ("Etamin", 17.943, 51.489, 2.23),
    ("Thuban", 14.073, 64.376, 3.65),
    ("Cor Caroli", 12.934, 38.318, 2.90),
    ("Deneb Kaitos", 0.726, -17.987, 2.04),
    ("Sadalmelik", 22.096, -0.320, 2.96),
    ("Sadalsuud", 21.526, -5.571, 2.91),
    ("Ankaa", 0.438, -42.306, 2.39),
    ("Gienah", 12.263, -17.542, 2.59),
    ("Porrima", 12.694, -1.449, 2.74),
    ("Vindemiatrix", 13.036, 10.959, 2.83),
    ("Acamar", 2.971, -40.305, 2.88),
    ("Menkent", 14.111, -36.370, 2.06),
    ("Naos", 8.059, -40.003, 2.25),
    ("Izar", 14.750, 27.074, 2.37),
    ("Muscida", 8.505, 60.718, 3.36),
    ("Alderamin", 21.310, 62.586, 2.51),
]


# Major constellation line patterns
# Each entry: (constellation_name, [(star_name_1, star_name_2), ...])
CONSTELLATION_LINES = [
    ("Ursa Major", [
        ("Dubhe", "Merak"), ("Merak", "Phecda"), ("Phecda", "Megrez"),
        ("Megrez", "Alioth"), ("Alioth", "Mizar"), ("Mizar", "Alkaid"),
        ("Megrez", "Dubhe"),
    ]),
    ("Orion", [
        ("Betelgeuse", "Bellatrix"), ("Bellatrix", "Mintaka"),
        ("Mintaka", "Alnilam"), ("Alnilam", "Alnitak"),
        ("Alnitak", "Saiph"), ("Betelgeuse", "Alnitak"),
        ("Bellatrix", "Rigel"), ("Rigel", "Saiph"),
    ]),
    ("Cassiopeia", [
        ("Schedar", "Caph"), ("Schedar", "Almach"),
    ]),
    ("Leo", [
        ("Regulus", "Denebola"),
    ]),
    ("Scorpius", [
        ("Antares", "Dschubba"), ("Antares", "Shaula"),
        ("Dschubba", "Graffias"),
    ]),
    ("Lyra", [
        ("Vega", "Vega"),  # single bright star
    ]),
    ("Cygnus", [
        ("Deneb", "Deneb"),  # single bright star
    ]),
    ("Aquila", [
        ("Altair", "Altair"),  # single bright star
    ]),
    ("Pegasus", [
        ("Markab", "Scheat"), ("Scheat", "Alpheratz"),
        ("Alpheratz", "Algenib"), ("Algenib", "Markab"),
    ]),
    ("Gemini", [
        ("Castor", "Pollux"), ("Castor", "Alhena"),
    ]),
    ("Canis Major", [
        ("Sirius", "Mirzam"), ("Sirius", "Adhara"), ("Sirius", "Wezen"),
    ]),
    ("Taurus", [
        ("Aldebaran", "Elnath"),
    ]),
    ("Virgo", [
        ("Spica", "Porrima"), ("Porrima", "Vindemiatrix"),
    ]),
    ("Bootes", [
        ("Arcturus", "Izar"),
    ]),
    ("Ursa Minor", [
        ("Polaris", "Kochab"),
    ]),
    ("Andromeda", [
        ("Alpheratz", "Mirach"), ("Mirach", "Almach"),
    ]),
    ("Libra", [
        ("Zubenelgenubi", "Zubeneschamali"),
    ]),
    ("Ophiuchus", [
        ("Rasalhague", "Sabik"),
    ]),
]


def _julian_date(dt: datetime) -> float:
    """Convert datetime to Julian Date."""
    y = dt.year
    m = dt.month
    d = dt.day + dt.hour / 24.0 + dt.minute / 1440.0 + dt.second / 86400.0

    if m <= 2:
        y -= 1
        m += 12

    A = int(y / 100)
    B = 2 - A + int(A / 4)
    return int(365.25 * (y + 4716)) + int(30.6001 * (m + 1)) + d + B - 1524.5


def _local_sidereal_time(dt: datetime, longitude: float) -> float:
    """Calculate Local Sidereal Time in degrees for a given UTC datetime and longitude."""
    jd = _julian_date(dt)
    T = (jd - 2451545.0) / 36525.0

    # Greenwich Mean Sidereal Time in degrees
    gmst = 280.46061837 + 360.98564736629 * (jd - 2451545.0) + \
           0.000387933 * T * T - T * T * T / 38710000.0
    gmst = gmst % 360.0

    # Local Sidereal Time
    lst = gmst + longitude
    return lst % 360.0


def _horizontal_coords(ra_hours: float, dec_deg: float, lst_deg: float, lat_deg: float):
    """Convert equatorial coordinates (RA/Dec) to horizontal (alt/az).

    Returns (altitude_deg, azimuth_deg).
    """
    ra_deg = ra_hours * 15.0  # Convert RA from hours to degrees
    ha_deg = lst_deg - ra_deg  # Hour angle

    ha = math.radians(ha_deg)
    dec = math.radians(dec_deg)
    lat = math.radians(lat_deg)

    sin_alt = math.sin(dec) * math.sin(lat) + math.cos(dec) * math.cos(lat) * math.cos(ha)
    alt = math.asin(max(-1.0, min(1.0, sin_alt)))

    cos_az = (math.sin(dec) - math.sin(alt) * math.sin(lat)) / (math.cos(alt) * math.cos(lat) + 1e-10)
    cos_az = max(-1.0, min(1.0, cos_az))
    az = math.acos(cos_az)
    if math.sin(ha) > 0:
        az = 2 * math.pi - az

    return math.degrees(alt), math.degrees(az)


def _stereographic_project(alt_deg: float, az_deg: float, radius: float):
    """Stereographic projection from horizontal coordinates to 2D circle.

    Projects the hemisphere above the horizon onto a circular viewport.
    Returns (x, y) centered at (0, 0) within a circle of given radius.
    """
    alt = math.radians(alt_deg)
    az = math.radians(az_deg)

    # Stereographic projection — zenith at center, horizon at edge
    r = radius * math.cos(alt) / (1.0 + math.sin(alt) + 1e-10)

    # Azimuth: North is up, East is right
    x = r * math.sin(az)
    y = -r * math.cos(az)  # Negative because we want North at top

    return x, y


def generate_star_map(
    lat: float,
    lon: float,
    dt: datetime,
    viewport_radius: float = 200.0,
    min_magnitude: float = 4.0,
) -> dict:
    """Generate star positions and constellation lines for a given location and time.

    Args:
        lat: Observer latitude in degrees
        lon: Observer longitude in degrees
        dt: UTC datetime for the observation
        viewport_radius: Radius of the circular star map in mm
        min_magnitude: Faintest magnitude to include (lower = fewer stars)

    Returns:
        dict with:
            - stars: list of (x, y, magnitude, name) projected onto viewport
            - constellation_lines: list of ((x1,y1), (x2,y2), constellation_name)
            - horizon_radius: radius of the viewport circle
    """
    # Ensure UTC
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    lst = _local_sidereal_time(dt, lon)

    # Project all stars above horizon
    star_positions = {}  # name -> (x, y, mag)
    projected_stars = []

    for name, ra, dec, mag in BRIGHT_STARS:
        if mag > min_magnitude:
            continue

        alt, az = _horizontal_coords(ra, dec, lst, lat)
        if alt < 0:
            continue  # Below horizon

        x, y = _stereographic_project(alt, az, viewport_radius)

        # Skip if outside viewport circle
        if x * x + y * y > viewport_radius * viewport_radius * 1.05:
            continue

        star_positions[name] = (x, y, mag)
        projected_stars.append({
            "x": round(x, 2),
            "y": round(y, 2),
            "magnitude": mag,
            "name": name,
        })

    # Build constellation lines from visible stars
    constellation_lines = []
    for const_name, pairs in CONSTELLATION_LINES:
        for star_a, star_b in pairs:
            if star_a == star_b:
                continue  # Skip self-referencing entries
            if star_a in star_positions and star_b in star_positions:
                ax, ay, _ = star_positions[star_a]
                bx, by, _ = star_positions[star_b]
                constellation_lines.append({
                    "x1": round(ax, 2),
                    "y1": round(ay, 2),
                    "x2": round(bx, 2),
                    "y2": round(by, 2),
                    "constellation": const_name,
                })

    return {
        "stars": projected_stars,
        "constellation_lines": constellation_lines,
        "horizon_radius": viewport_radius,
    }


def generate_star_map_svg(
    star_data: dict,
    board_w: float,
    board_h: float,
    location_name: str,
    subtitle: str = "",
    show_coordinates: bool = True,
    lat: float = 0.0,
    lon: float = 0.0,
    date_str: str = "",
    font_family: str = "serif",
    font_size_mm: float = 14.0,
    color_theme: str = "midnight",
    output_mode: str = "print",
) -> dict:
    """Generate a complete star map SVG poster.

    Returns dict with: svg, node_count, path_count, layer_count
    """
    from app.services.thumbnail_generator import get_poster_theme

    # Star maps always look best with dark themes
    theme = get_poster_theme(color_theme)

    stars = star_data["stars"]
    lines = star_data["constellation_lines"]
    radius = star_data["horizon_radius"]

    # Center of the map area
    mat_pct = 0.07
    mat_x = round(board_w * mat_pct, 2)
    mat_y = round(board_h * mat_pct, 2)
    text_area_h = round(board_h * 0.14, 2)
    map_w = round(board_w - 2 * mat_x, 2)
    map_h = round(board_h - mat_y - text_area_h - mat_y, 2)

    cx = round(mat_x + map_w / 2, 2)
    cy = round(mat_y + map_h / 2, 2)

    # Scale viewport to fit the map area
    fit_radius = min(map_w, map_h) / 2 * 0.92
    scale = fit_radius / radius if radius > 0 else 1.0

    # Font family
    FONT_FAMILIES = {
        "sans": "Arial, Helvetica, sans-serif",
        "serif": "Georgia, 'Times New Roman', Times, serif",
        "script": "'Brush Script MT', 'Segoe Script', cursive",
        "mono": "'Courier New', Courier, monospace",
    }
    ff = FONT_FAMILIES.get(font_family, FONT_FAMILIES["serif"])

    path_count = len(stars) + len(lines) + 2  # stars + lines + circle + bg
    node_count = len(stars) * 2 + len(lines) * 2
    layer_count = 5  # bg, circle, constellations, stars, text

    is_print = output_mode == "print"

    # Determine colors based on mode
    if is_print:
        bg_color = theme.get("map_bg", "#0f1923")
        mat_color = theme.get("mat", "#ffffff")
        star_color = "#ffffff"
        constellation_color = "rgba(255,255,255,0.15)"
        text_primary = theme.get("text_primary", "#1a1a1a")
        text_secondary = theme.get("text_secondary", "#666666")
        circle_stroke = "rgba(255,255,255,0.3)"
        label_color = "rgba(255,255,255,0.4)"
    else:
        bg_color = "#ffffff"
        mat_color = "#ffffff"
        star_color = "#1a1a1a"
        constellation_color = "#cccccc"
        text_primary = "#1a1a1a"
        text_secondary = "#666666"
        circle_stroke = "#999999"
        label_color = "#999999"

    svg_lines = []
    svg_lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    svg_lines.append(
        f'<svg xmlns="http://www.w3.org/2000/svg"'
        f' width="{board_w}mm" height="{board_h}mm"'
        f' viewBox="0 0 {board_w} {board_h}">'
    )

    svg_lines.append(f"  <!-- MapForge Star Map v1.0 | Theme: {color_theme} -->")
    svg_lines.append(f"  <!-- Location: {_escape(location_name)} -->")
    svg_lines.append(f"  <!-- Date: {date_str} -->")
    svg_lines.append("")

    # Background
    svg_lines.append('  <g id="poster_background">')
    svg_lines.append(f'    <rect width="{board_w}" height="{board_h}" fill="{mat_color}"/>')
    svg_lines.append("  </g>")
    svg_lines.append("")

    # Map area background (dark for star maps)
    svg_lines.append('  <g id="star_field">')
    svg_lines.append(
        f'    <rect x="{mat_x}" y="{mat_y}" width="{map_w}" height="{map_h}"'
        f' fill="{bg_color}"/>'
    )
    svg_lines.append("  </g>")
    svg_lines.append("")

    # Clip to circle
    svg_lines.append("  <defs>")
    svg_lines.append(f'    <clipPath id="star_clip">')
    svg_lines.append(f'      <circle cx="{cx}" cy="{cy}" r="{round(fit_radius, 2)}"/>')
    svg_lines.append("    </clipPath>")
    # Radial gradient for subtle glow
    svg_lines.append(f'    <radialGradient id="star_glow" cx="50%" cy="50%" r="50%">')
    svg_lines.append(f'      <stop offset="0%" stop-color="{bg_color}" stop-opacity="1"/>')
    svg_lines.append(f'      <stop offset="85%" stop-color="{bg_color}" stop-opacity="1"/>')
    svg_lines.append(f'      <stop offset="100%" stop-color="{bg_color}" stop-opacity="0.6"/>')
    svg_lines.append("    </radialGradient>")
    svg_lines.append("  </defs>")
    svg_lines.append("")

    # Horizon circle
    svg_lines.append('  <g id="horizon">')
    svg_lines.append(
        f'    <circle cx="{cx}" cy="{cy}" r="{round(fit_radius, 2)}"'
        f' fill="none" stroke="{circle_stroke}" stroke-width="0.5"/>'
    )
    svg_lines.append("  </g>")
    svg_lines.append("")

    # Constellation lines
    svg_lines.append(f'  <g id="constellations" clip-path="url(#star_clip)">')
    for line in lines:
        x1 = round(cx + line["x1"] * scale, 2)
        y1 = round(cy + line["y1"] * scale, 2)
        x2 = round(cx + line["x2"] * scale, 2)
        y2 = round(cy + line["y2"] * scale, 2)
        svg_lines.append(
            f'    <line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}"'
            f' stroke="{constellation_color}" stroke-width="0.3"'
            f' stroke-linecap="round"/>'
        )
    svg_lines.append("  </g>")
    svg_lines.append("")

    # Stars — size inversely proportional to magnitude
    svg_lines.append(f'  <g id="stars" clip-path="url(#star_clip)">')
    for star in stars:
        sx = round(cx + star["x"] * scale, 2)
        sy = round(cy + star["y"] * scale, 2)
        mag = star["magnitude"]

        # Star radius: brighter = bigger
        # mag -1.5 → r=2.0, mag 0 → r=1.4, mag 2 → r=0.8, mag 4 → r=0.4
        r = max(0.3, round(2.0 - mag * 0.4, 2))

        # Bright stars get a subtle glow in print mode
        if is_print and mag < 1.0:
            glow_r = round(r * 3, 2)
            svg_lines.append(
                f'    <circle cx="{sx}" cy="{sy}" r="{glow_r}"'
                f' fill="{star_color}" opacity="0.08"/>'
            )

        svg_lines.append(
            f'    <circle cx="{sx}" cy="{sy}" r="{r}"'
            f' fill="{star_color}"/>'
        )

        # Label bright stars
        if mag < 1.5 and is_print:
            label_size = round(font_size_mm * 0.22, 2)
            svg_lines.append(
                f'    <text x="{round(sx + r + 1, 2)}" y="{round(sy + label_size * 0.35, 2)}"'
                f' font-family="{ff}" font-size="{label_size}"'
                f' fill="{label_color}">{_escape(star["name"])}</text>'
            )
    svg_lines.append("  </g>")
    svg_lines.append("")

    # Cardinal directions
    dir_size = round(font_size_mm * 0.4, 2)
    directions = [
        ("N", cx, cy - fit_radius - dir_size * 1.5),
        ("S", cx, cy + fit_radius + dir_size * 2),
        ("E", cx + fit_radius + dir_size, cy + dir_size * 0.35),
        ("W", cx - fit_radius - dir_size, cy + dir_size * 0.35),
    ]
    svg_lines.append('  <g id="cardinal_directions">')
    for label, dx, dy in directions:
        svg_lines.append(
            f'    <text x="{round(dx, 2)}" y="{round(dy, 2)}"'
            f' text-anchor="middle" font-family="{ff}"'
            f' font-size="{dir_size}" fill="{text_secondary if is_print else "#888888"}"'
            f' letter-spacing="{round(dir_size * 0.3, 2)}">{label}</text>'
        )
    svg_lines.append("  </g>")
    svg_lines.append("")

    # Thin frame around map area
    inset = 1.5
    svg_lines.append('  <g id="map_frame">')
    svg_lines.append(
        f'    <rect x="{mat_x}" y="{mat_y}" width="{map_w}" height="{map_h}"'
        f' fill="none" stroke="{text_secondary}" stroke-width="0.6" opacity="0.5"/>'
    )
    svg_lines.append(
        f'    <rect x="{round(mat_x - inset, 2)}" y="{round(mat_y - inset, 2)}"'
        f' width="{round(map_w + 2 * inset, 2)}" height="{round(map_h + 2 * inset, 2)}"'
        f' fill="none" stroke="{text_secondary}" stroke-width="0.25" opacity="0.3"/>'
    )
    svg_lines.append("  </g>")
    svg_lines.append("")

    # Separator line
    sep_y = round(mat_y + map_h + text_area_h * 0.15, 2)
    sep_margin = round(board_w * 0.25, 2)
    svg_lines.append(
        f'  <line x1="{sep_margin}" y1="{sep_y}" x2="{round(board_w - sep_margin, 2)}" y2="{sep_y}"'
        f' stroke="{text_secondary}" stroke-width="0.3" opacity="0.4"/>'
    )
    svg_lines.append("")

    # Text area
    text_center_x = round(board_w / 2, 2)
    text_start_y = round(sep_y + text_area_h * 0.28, 2)

    title_size = round(font_size_mm * 1.6, 2)
    subtitle_size = round(font_size_mm * 0.65, 2)
    coord_size = round(font_size_mm * 0.45, 2)

    svg_lines.append('  <g id="poster_text">')
    svg_lines.append(
        f'    <text x="{text_center_x}" y="{round(text_start_y, 2)}"'
        f' text-anchor="middle" font-family="{ff}"'
        f' font-size="{title_size}" font-weight="bold"'
        f' letter-spacing="{round(title_size * 0.2, 2)}"'
        f' fill="{text_primary}">{_escape(location_name.upper())}</text>'
    )

    next_y = text_start_y + title_size * 1.1

    # Date subtitle (auto-generated if no subtitle given)
    display_subtitle = subtitle or date_str
    if display_subtitle:
        svg_lines.append(
            f'    <text x="{text_center_x}" y="{round(next_y, 2)}"'
            f' text-anchor="middle" font-family="{ff}"'
            f' font-size="{subtitle_size}" font-weight="300"'
            f' letter-spacing="{round(subtitle_size * 0.25, 2)}"'
            f' fill="{text_secondary}">{_escape(display_subtitle)}</text>'
        )
        next_y += subtitle_size * 1.6
        layer_count += 1

    if show_coordinates:
        lat_dir = "N" if lat >= 0 else "S"
        lon_dir = "W" if lon < 0 else "E"
        coord_text = f"{abs(lat):.4f}\u00b0 {lat_dir}  /  {abs(lon):.4f}\u00b0 {lon_dir}"
        svg_lines.append(
            f'    <text x="{text_center_x}" y="{round(next_y, 2)}"'
            f' text-anchor="middle" font-family="{ff}"'
            f' font-size="{coord_size}"'
            f' letter-spacing="{round(coord_size * 0.15, 2)}"'
            f' fill="{text_secondary}">{coord_text}</text>'
        )

    svg_lines.append("  </g>")
    svg_lines.append("")
    svg_lines.append("</svg>")

    return {
        "svg": "\n".join(svg_lines),
        "node_count": node_count,
        "path_count": path_count,
        "layer_count": layer_count,
    }


def _escape(text: str) -> str:
    """Escape special XML characters."""
    return (
        text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )
