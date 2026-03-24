"""Dynamic pricing engine for customer-facing map orders.

Price is calculated based on:
  - Base price by product type
  - Size multiplier
  - Add-on fees (contours, streets, markers, high DPI, etc.)
"""

# Base prices in cents by product type
BASE_PRICE_CENTS = {
    "province": 799,     # $7.99
    "city": 999,         # $9.99
    "lake": 1199,        # $11.99
    "park": 999,         # $9.99
    "community": 899,    # $8.99
    "name_sign": 1299,   # $12.99
}

# Size multiplier (relative to base price)
SIZE_MULTIPLIER = {
    "print_8x10": 1.0,
    "print_11x14": 1.2,
    "print_16x20": 1.4,
    "print_18x24": 1.6,
    "print_24x36": 2.0,
    # CNC sizes
    "small": 1.0,
    "medium": 1.3,
    "large": 1.6,
    "xl": 2.0,
    "max": 2.5,
    "custom": 1.5,
}

# Add-on fees in cents
ADDON_FEES = {
    "include_streets": 200,      # +$2.00
    "include_contours": 400,     # +$4.00
    "markers": 100,              # +$1.00 per marker
    "heart_marker": 100,         # +$1.00
    "high_dpi": 200,             # +$2.00 (600 DPI vs 300)
    "border_thin": 0,
    "border_double": 100,        # +$1.00
    "border_ornate": 200,        # +$2.00
    "include_bleed": 0,
    "include_crop_marks": 0,
}

# Format add-ons (what's included vs. extra)
FORMAT_FEES = {
    "svg": 0,                    # included
    "png": 0,                    # included
    "dxf": 300,                  # +$3.00
    "stl": 500,                  # +$5.00
}


def calculate_price(
    product_type: str,
    board_size: str,
    include_streets: bool = False,
    include_contours: bool = False,
    num_markers: int = 0,
    has_heart: bool = False,
    print_dpi: int = 300,
    border_style: str = "none",
    include_dxf: bool = False,
    include_stl: bool = False,
) -> dict:
    """Calculate the total price for a design.

    Returns dict with breakdown:
      {
        "base_cents": 999,
        "size_label": "16x20\"",
        "size_multiplier": 1.4,
        "addons": [{"label": "Street overlay", "cents": 200}, ...],
        "subtotal_cents": 1599,
        "total_cents": 1599,
        "total_display": "$15.99",
      }
    """
    base = BASE_PRICE_CENTS.get(product_type, 999)
    multiplier = SIZE_MULTIPLIER.get(board_size, 1.0)

    base_after_size = int(base * multiplier)

    addons = []

    if include_streets:
        addons.append({"label": "Street overlay", "cents": ADDON_FEES["include_streets"]})

    if include_contours:
        addons.append({"label": "Depth/elevation contours", "cents": ADDON_FEES["include_contours"]})

    if num_markers > 0:
        fee = ADDON_FEES["markers"] * num_markers
        addons.append({"label": f"Custom markers ({num_markers})", "cents": fee})

    if has_heart:
        addons.append({"label": "Heart marker", "cents": ADDON_FEES["heart_marker"]})

    if print_dpi >= 600:
        addons.append({"label": "High resolution (600 DPI)", "cents": ADDON_FEES["high_dpi"]})

    if border_style == "double":
        addons.append({"label": "Double frame border", "cents": ADDON_FEES["border_double"]})
    elif border_style == "ornate":
        addons.append({"label": "Ornate corner border", "cents": ADDON_FEES["border_ornate"]})

    if include_dxf:
        addons.append({"label": "DXF file (CNC)", "cents": FORMAT_FEES["dxf"]})

    if include_stl:
        addons.append({"label": "3D STL file", "cents": FORMAT_FEES["stl"]})

    addon_total = sum(a["cents"] for a in addons)
    total = base_after_size + addon_total

    # Size label for display
    size_labels = {
        "print_8x10": '8x10"', "print_11x14": '11x14"', "print_16x20": '16x20"',
        "print_18x24": '18x24"', "print_24x36": '24x36"',
        "small": '12x16"', "medium": '16x20"', "large": '20x24"',
        "xl": '24x32"', "max": '32x48"', "custom": "Custom",
    }

    return {
        "base_cents": base,
        "size_label": size_labels.get(board_size, board_size),
        "size_multiplier": multiplier,
        "base_after_size_cents": base_after_size,
        "addons": addons,
        "addon_total_cents": addon_total,
        "total_cents": total,
        "total_display": f"${total / 100:.2f}",
    }
