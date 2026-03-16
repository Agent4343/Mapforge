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
        dxfattribs={"layer": "BOARD_OUTLINE", "linetype": "DASHED"},
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
        coord_text = f"{abs(lat):.4f} {lat_dir}, {abs(lon):.4f} {lon_dir}"

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

    # Write to bytes
    stream = io.BytesIO()
    doc.write(stream)
    return stream.getvalue()
