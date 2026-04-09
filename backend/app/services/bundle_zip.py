"""Customer bundle ZIP builder.

Builds the digital-download ZIP that Etsy buyers receive after purchase.
Used by both:
  - /api/v1/download/{file_id}/etsy-package (admin, includes listing.txt)
  - /api/v1/orders/download/{token}?format=zip (customer, no listing.txt)
"""

import io
import re
import zipfile

from app.logging_config import log
from app.models.db_models import GeneratedFile
from app.services.file_storage import retrieve_file
from app.services.thumbnail_generator import generate_wall_mockup


def seo_filename(location_name: str, ext: str, suffix: str = "") -> str:
    """Generate an SEO-friendly filename from location name."""
    clean = re.sub(r"[^a-zA-Z0-9\s-]", "", location_name)
    clean = re.sub(r"\s+", "-", clean.strip()).lower()
    if not clean:
        clean = "map"
    parts = ["mapforge", clean]
    if suffix:
        parts.append(suffix)
    return "-".join(parts) + f".{ext}"


def _readme_text(location: str, seo_name: str) -> str:
    """Buyer-facing how-to-print instructions bundled with every download."""
    return "\n".join([
        f"=== Thank you for your {location} Map Art purchase! ===",
        "",
        "This is an INSTANT DIGITAL DOWNLOAD — no physical product will be shipped.",
        "",
        "WHAT'S IN THIS BUNDLE",
        "---------------------",
        f"  - {seo_name}-print.png   <-- START HERE. This is your wall art poster.",
        "                             High-resolution 300 DPI PNG, ready to print",
        "                             and frame at standard sizes.",
        "",
        f"  - {seo_name}.svg         Full-detail vector source. Use this if you",
        "                             want to scale up beyond 24x36 inches or",
        "                             edit the design in Illustrator/Inkscape.",
        "",
        f"  - {seo_name}-cnc.svg     Simplified CNC-ready vector (major roads only).",
        f"  - {seo_name}.dxf         DXF file for CAD/CAM software.",
        "                             Bonus files for CNC hobbyists and laser cutters",
        "                             (VCarve Pro, Fusion 360, Carbide Create, LightBurn,",
        "                             Easel). Works on wood, acrylic, plywood, and MDF.",
        "",
        f"  - {seo_name}-wall-mockup-light_wall.png",
        f"  - {seo_name}-wall-mockup-dark_wall.png",
        "                             Lifestyle mockups showing the map framed on a wall.",
        "                             Share on social or use as a preview.",
        "",
        "HOW TO PRINT YOUR WALL ART",
        "--------------------------",
        "1. Choose a frame size. The PNG prints beautifully at any of these:",
        "        8x10 inches   (small desk print)",
        "       11x14 inches   (accent piece)",
        "       16x20 inches   (standard wall art)",
        "       18x24 inches   (statement piece)",
        "       24x36 inches   (large centerpiece)",
        "",
        "2. Pick a print service. Any of these work great:",
        "     - At home on a color inkjet or laser printer",
        "     - Local print shop (Staples, FedEx Office, Michael's)",
        "     - Online print service (Shutterfly, Mpix, Printful, Printique)",
        "",
        "3. Frame it. Any standard off-the-shelf frame from IKEA, Target,",
        "   Amazon, or Michael's will fit — no custom framing needed.",
        "",
        "TIPS",
        "----",
        "  - Print on matte or semi-gloss paper for the best look.",
        "  - If printing larger than 18x24, use the SVG file for maximum sharpness.",
        "  - Cardstock (80-100 lb) is a great home-print choice.",
        "",
        "LICENSE",
        "-------",
        "For personal use and small-batch handmade resale (wood-carved or",
        "laser-cut maps you sell yourself). Not for mass-produced resale.",
        "Map data: OpenStreetMap contributors (ODbL).",
        "",
        "Questions? Message us through Etsy — we respond within 24 hours.",
        "",
        "Happy decorating!",
        "— MapForge",
    ])


async def build_customer_bundle_zip(
    file_record: GeneratedFile,
    extra_files: dict[str, bytes] | None = None,
) -> bytes:
    """Build the complete customer-facing ZIP bundle.

    Returns the raw ZIP bytes. Silently skips any file that failed to
    generate during the original /generate call — the bundle is built
    best-effort so the customer always gets something downloadable.

    Contents (on a successful generation):
      - {name}-print.png                      PRIMARY wall art poster
      - {name}.svg                            full-detail vector source
      - {name}-cnc.svg                        CNC-optimized vector
      - {name}.dxf                            DXF for CAD/CAM
      - {name}.stl                            STL 3D mesh (if contours)
      - {name}-mockup.png                     thumbnail mockup
      - {name}-wall-mockup-light_wall.png     lifestyle mockup (generated on the fly)
      - {name}-wall-mockup-dark_wall.png      lifestyle mockup (generated on the fly)
      - README_FIRST.txt                      how-to-print instructions

    Callers may pass `extra_files` (a mapping of zip-member-name -> bytes)
    to append additional files — used by the admin endpoint to add
    listing.txt (AI copy for the seller) and the Etsy hero image.
    """
    location = file_record.location_name or "Map"
    seo_name = seo_filename(location, "").rstrip(".")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # 1. Primary wall art poster (high-res print PNG) — most important file
        if file_record.print_png_key:
            png_bytes = await retrieve_file(file_record.print_png_key)
            if png_bytes:
                zf.writestr(f"{seo_name}-print.png", png_bytes)

        # 2. Full-detail SVG source vector
        svg_bytes = None
        if file_record.svg_storage_key:
            svg_bytes = await retrieve_file(file_record.svg_storage_key)
            if svg_bytes:
                zf.writestr(f"{seo_name}.svg", svg_bytes)

        # 3. CNC-optimized SVG (bonus for CNC hobbyists)
        if file_record.svg_storage_key:
            cnc_key = file_record.svg_storage_key.replace("svg/", "cnc/").replace(
                ".svg", "_cnc.svg"
            )
            cnc_bytes = await retrieve_file(cnc_key)
            if cnc_bytes:
                zf.writestr(f"{seo_name}-cnc.svg", cnc_bytes)

        # 4. DXF (bonus for CAD/CAM users)
        if file_record.dxf_storage_key:
            dxf_bytes = await retrieve_file(file_record.dxf_storage_key)
            if dxf_bytes:
                zf.writestr(f"{seo_name}.dxf", dxf_bytes)

        # 5. STL 3D mesh (only present when contours were enabled)
        if file_record.svg_storage_key:
            stl_key = file_record.svg_storage_key.replace("svg/", "stl/").replace(
                ".svg", ".stl"
            )
            stl_bytes = await retrieve_file(stl_key)
            if stl_bytes:
                zf.writestr(f"{seo_name}.stl", stl_bytes)

        # 6. Thumbnail / product mockup
        if file_record.thumbnail_key:
            thumb_bytes = await retrieve_file(file_record.thumbnail_key)
            if thumb_bytes:
                zf.writestr(f"{seo_name}-mockup.png", thumb_bytes)

        # 7. Wall-framed lifestyle mockups (generated on the fly from the SVG)
        if svg_bytes:
            try:
                for mockup_style in ("light_wall", "dark_wall"):
                    mockup_png = generate_wall_mockup(
                        svg_bytes.decode("utf-8"),
                        output_width=3000,
                        output_height=2400,
                        mockup_style=mockup_style,
                    )
                    zf.writestr(
                        f"{seo_name}-wall-mockup-{mockup_style}.png", mockup_png
                    )
            except Exception as e:
                log.warning(f"Wall mockup generation failed (non-fatal): {e}")

        # 8. Buyer-facing README with print instructions
        zf.writestr("README_FIRST.txt", _readme_text(location, seo_name))

        # 9. Any caller-provided extras (e.g., admin's listing.txt, Etsy hero)
        if extra_files:
            for name, data in extra_files.items():
                if data:
                    zf.writestr(name, data)

    return buf.getvalue()
