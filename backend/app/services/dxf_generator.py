"""DXF export engine for CNC-ready output.

Generates DXF files from the same processed geometry used for SVG generation.
DXF files import directly into VCarve Pro, AutoCAD, and other CAM software.
"""

import io
import math

import ezdxf
from ezdxf.enums import TextEntityAlignment

from app.services.geometry_processor import transform_wgs84_to_board


def generate_dxf(
    processed: dict,
    location_name: str,
    show_coordinates: bool = True,
    font_size_mm: float = 14.0,
    center_latlon: tuple[float, float] | None = None,
    streets_data: dict | None = None,
    water_data: dict | None = None,
    contour_data: list[dict] | None = None,
    pin_location: tuple[float, float] | None = None,
    markers: list[dict] | None = None,
) -> bytes:
    """Generate a CNC-ready DXF file from processed geometry.

    Returns DXF file as bytes.
    """
    board_w, board_h = processed["board_mm"]
    polygons = processed["polygons"]
    latlon = center_latlon or processed.get("center_latlon", (0, 0))

    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 4  # millimeters

    msp = doc.modelspace()

    # Create layers matching SVG layer structure
    doc.layers.add("BOARD_OUTLINE", color=8)        # gray
    doc.layers.add("GEOGRAPHY_OUTLINE", color=7)     # white/black
    doc.layers.add("GEOGRAPHY_FILL", color=7)
    doc.layers.add("TEXT_PRIMARY", color=7)
    doc.layers.add("TEXT_COORDINATES", color=8)

    # Board outline (dashed)
    msp.add_lwpolyline(
        [(0, 0), (board_w, 0), (board_w, board_h), (0, board_h), (0, 0)],
        dxfattribs={"layer": "BOARD_OUTLINE"},
    )

    # Geography outlines
    for exterior, holes in polygons:
        if len(exterior) >= 3:
            # Flip Y for DXF (origin bottom-left)
            dxf_coords = [(x, board_h - y) for x, y in exterior]
            msp.add_lwpolyline(
                dxf_coords,
                close=True,
                dxfattribs={"layer": "GEOGRAPHY_OUTLINE"},
            )

        for hole in holes:
            if len(hole) >= 3:
                dxf_coords = [(x, board_h - y) for x, y in hole]
                msp.add_lwpolyline(
                    dxf_coords,
                    close=True,
                    dxfattribs={"layer": "GEOGRAPHY_OUTLINE"},
                )

    # Text — location name
    text_y = font_size_mm * 2.5  # distance from bottom (DXF is bottom-up)
    msp.add_text(
        location_name.upper(),
        height=font_size_mm,
        dxfattribs={
            "layer": "TEXT_PRIMARY",
            "style": "Standard",
        },
    ).set_placement(
        (board_w / 2, text_y),
        align=TextEntityAlignment.BOTTOM_CENTER,
    )

    # Coordinates text
    if show_coordinates and latlon:
        lat, lon = latlon
        lat_dir = "N" if lat >= 0 else "S"
        lon_dir = "W" if lon < 0 else "E"
        coord_text = f"{abs(lat):.6f} {lat_dir}  /  {abs(lon):.6f} {lon_dir}"

        coord_y = text_y - font_size_mm * 1.2
        msp.add_text(
            coord_text,
            height=font_size_mm * 0.45,
            dxfattribs={
                "layer": "TEXT_COORDINATES",
                "style": "Standard",
            },
        ).set_placement(
            (board_w / 2, coord_y),
            align=TextEntityAlignment.BOTTOM_CENTER,
        )

    # Water features (lakes, rivers, streams)
    if water_data:
        transform = processed.get("transform")
        doc.layers.add("WATER_POLYGONS", color=4)   # cyan
        doc.layers.add("WATERWAYS", color=4)

        for coords, water_type, name in water_data.get("water_polygons", []):
            if len(coords) < 3:
                continue
            board_coords = transform_wgs84_to_board(coords, transform) if transform else coords
            dxf_coords = [(x, board_h - y) for x, y in board_coords]
            msp.add_lwpolyline(
                dxf_coords,
                close=True,
                dxfattribs={"layer": "WATER_POLYGONS"},
            )

        for coords, water_type, name in water_data.get("waterways", []):
            if len(coords) < 2:
                continue
            board_coords = transform_wgs84_to_board(coords, transform) if transform else coords
            dxf_coords = [(x, board_h - y) for x, y in board_coords]
            msp.add_lwpolyline(
                dxf_coords,
                close=False,
                dxfattribs={"layer": "WATERWAYS"},
            )

    # Contour/depth bands
    if contour_data:
        doc.layers.add("CONTOURS", color=9)  # light blue
        for band in contour_data:
            for contour in band.get("contours", []):
                coords = contour.get("coords", [])
                if len(coords) < 2:
                    continue
                transform = processed.get("transform")
                board_coords = transform_wgs84_to_board(coords, transform) if transform else coords
                dxf_coords = [(x, board_h - y) for x, y in board_coords]
                msp.add_lwpolyline(
                    dxf_coords,
                    close=False,
                    dxfattribs={"layer": "CONTOURS"},
                )

    # Streets and street labels
    if streets_data:
        transform = processed.get("transform")
        doc.layers.add("STREETS", color=8)
        doc.layers.add("STREET_LABELS", color=8)

        label_font_sizes = {"major": 2.5, "minor": 1.8}
        best_segments: dict[str, tuple] = {}

        for road_type_key in ("major_roads", "minor_roads"):
            road_type = "major" if "major" in road_type_key else "minor"
            for coords, road_class, width, name in streets_data.get(road_type_key, []):
                if len(coords) < 2:
                    continue
                board_coords = transform_wgs84_to_board(coords, transform) if transform else coords
                # DXF: flip Y (origin bottom-left)
                dxf_coords = [(x, board_h - y) for x, y in board_coords]
                msp.add_lwpolyline(
                    dxf_coords,
                    close=False,
                    dxfattribs={"layer": "STREETS"},
                )
                if name:
                    seg_len = sum(
                        math.hypot(board_coords[i][0] - board_coords[i-1][0],
                                   board_coords[i][1] - board_coords[i-1][1])
                        for i in range(1, len(board_coords))
                    )
                    existing = best_segments.get(name)
                    if existing is None or seg_len > existing[0]:
                        best_segments[name] = (seg_len, board_coords, road_type)

        # Place labels for longest segment of each named street
        for name, (seg_len, bcoords, road_type) in best_segments.items():
            font_size = label_font_sizes[road_type]
            approx_width = len(name) * font_size * 0.55
            if seg_len < approx_width * 1.2:
                continue

            # Find midpoint
            half = seg_len / 2.0
            traveled = 0.0
            mid_x, mid_y, angle = bcoords[0][0], bcoords[0][1], 0.0
            for i in range(1, len(bcoords)):
                dx = bcoords[i][0] - bcoords[i-1][0]
                dy = bcoords[i][1] - bcoords[i-1][1]
                sl = math.hypot(dx, dy)
                if traveled + sl >= half and sl > 0:
                    frac = (half - traveled) / sl
                    mid_x = bcoords[i-1][0] + dx * frac
                    mid_y = bcoords[i-1][1] + dy * frac
                    angle = math.degrees(math.atan2(dy, dx))
                    break
                traveled += sl

            # Flip Y for DXF and adjust angle
            dxf_mid_y = board_h - mid_y
            dxf_angle = -angle  # DXF Y is flipped
            if dxf_angle > 90:
                dxf_angle -= 180
            elif dxf_angle < -90:
                dxf_angle += 180

            msp.add_text(
                name.upper(),
                height=font_size,
                rotation=dxf_angle,
                dxfattribs={
                    "layer": "STREET_LABELS",
                    "style": "Standard",
                },
            ).set_placement(
                (mid_x, dxf_mid_y),
                align=TextEntityAlignment.MIDDLE_CENTER,
            )

    # Pin marker for name_sign / location marking
    if pin_location:
        px, py_svg = pin_location
        py = board_h - py_svg  # flip Y for DXF
        r = font_size_mm * 0.2
        doc.layers.add("PIN_MARKER", color=1)  # red

        # Circle
        msp.add_circle(
            center=(px, py),
            radius=r,
            dxfattribs={"layer": "PIN_MARKER"},
        )
        # Diamond pointer below
        h = font_size_mm * 0.7
        msp.add_lwpolyline(
            [
                (px, py - r),
                (px - r * 0.6, py - r - h * 0.35),
                (px, py - r - h),
                (px + r * 0.6, py - r - h * 0.35),
                (px, py - r),
            ],
            close=True,
            dxfattribs={"layer": "PIN_MARKER"},
        )

    # Custom markers (Home, Cottage, etc.)
    if markers:
        doc.layers.add("CUSTOM_MARKERS", color=1)  # red
        doc.layers.add("MARKER_LABELS", color=7)
        r = font_size_mm * 0.18
        label_size = font_size_mm * 0.3

        for m in markers:
            mx = m["x"]
            my_svg = m["y"]
            my = board_h - my_svg  # flip Y for DXF
            label = m.get("label", "")
            icon = m.get("icon", "pin")

            # Skip out-of-bounds
            if mx < 0 or mx > board_w or my_svg < 0 or my_svg > board_h:
                continue

            # All icons rendered as circle + label in DXF for CAM compatibility
            msp.add_circle(
                center=(mx, my),
                radius=r,
                dxfattribs={"layer": "CUSTOM_MARKERS"},
            )

            # Diamond pointer below circle (for pin/diamond icons)
            if icon in ("pin", "diamond"):
                h = r * 2.5
                msp.add_lwpolyline(
                    [
                        (mx, my - r),
                        (mx - r * 0.5, my - r - h * 0.3),
                        (mx, my - r - h),
                        (mx + r * 0.5, my - r - h * 0.3),
                        (mx, my - r),
                    ],
                    close=True,
                    dxfattribs={"layer": "CUSTOM_MARKERS"},
                )

            # Star points (for star icon)
            if icon == "star":
                outer_r = r * 1.2
                inner_r = r * 0.5
                pts = []
                for i in range(5):
                    angle_outer = math.radians(-90 + i * 72)
                    pts.append((mx + outer_r * math.cos(angle_outer), my + outer_r * math.sin(angle_outer)))
                    angle_inner = math.radians(-90 + i * 72 + 36)
                    pts.append((mx + inner_r * math.cos(angle_inner), my + inner_r * math.sin(angle_inner)))
                pts.append(pts[0])
                msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": "CUSTOM_MARKERS"})

            # Label
            if label:
                label_y = my - r * 2.8  # below marker (DXF Y-flipped)
                msp.add_text(
                    label.upper(),
                    height=label_size,
                    dxfattribs={
                        "layer": "MARKER_LABELS",
                        "style": "Standard",
                    },
                ).set_placement(
                    (mx, label_y),
                    align=TextEntityAlignment.TOP_CENTER,
                )

    # Write to bytes — ezdxf writes text to a StringIO, then encode
    stream = io.StringIO()
    doc.write(stream)
    return stream.getvalue().encode("utf-8")
