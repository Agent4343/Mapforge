"""DXF export engine for CNC-ready output.

Generates DXF files from the same processed geometry used for SVG generation.
DXF files import directly into VCarve Pro, AutoCAD, and other CAM software.
"""

import io

import ezdxf
from ezdxf.enums import TextEntityAlignment


def generate_dxf(
    processed: dict,
    location_name: str,
    show_coordinates: bool = True,
    font_size_mm: float = 14.0,
    center_latlon: tuple[float, float] | None = None,
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

    # Write to bytes
    stream = io.BytesIO()
    doc.write(stream)
    return stream.getvalue()
