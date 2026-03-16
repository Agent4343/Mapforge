#!/usr/bin/env python3
"""Generate clean map designs for Etsy marketplace listings.

Batch-generates SVG, DXF, and PNG mockup files for Canadian provinces,
US states, and Canadian cities with Etsy-optimized settings.
Requires a Pro or Admin account.

Usage:
    # Generate all provinces + states (default):
    python scripts/generate_etsy_catalog.py --base-url http://localhost:8000 --token YOUR_JWT

    # Generate Canadian cities with street maps:
    python scripts/generate_etsy_catalog.py --base-url http://localhost:8000 --token YOUR_JWT --type cities

    # Generate everything (provinces + states + cities):
    python scripts/generate_etsy_catalog.py --base-url http://localhost:8000 --token YOUR_JWT --type all

    # Only Canadian provinces:
    python scripts/generate_etsy_catalog.py --base-url http://localhost:8000 --token YOUR_JWT --country ca --type provinces

    # All three cut styles:
    python scripts/generate_etsy_catalog.py --base-url http://localhost:8000 --token YOUR_JWT --all-styles
"""

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

# Canadian provinces and territories with OSM relation IDs
CA_PROVINCES = [
    {"name": "Ontario", "osm_id": 68841},
    {"name": "Quebec", "osm_id": 61549},
    {"name": "British Columbia", "osm_id": 390867},
    {"name": "Alberta", "osm_id": 391186},
    {"name": "Manitoba", "osm_id": 390840},
    {"name": "Saskatchewan", "osm_id": 391178},
    {"name": "Nova Scotia", "osm_id": 390558},
    {"name": "New Brunswick", "osm_id": 68942},
    {"name": "Prince Edward Island", "osm_id": 391115},
    {"name": "Newfoundland and Labrador", "osm_id": 391196},
    {"name": "Northwest Territories", "osm_id": 391220},
    {"name": "Yukon", "osm_id": 391455},
    {"name": "Nunavut", "osm_id": 390847},
]

# All 50 US states with OSM relation IDs
US_STATES = [
    {"name": "Alabama", "osm_id": 161950},
    {"name": "Alaska", "osm_id": 1116270},
    {"name": "Arizona", "osm_id": 162018},
    {"name": "Arkansas", "osm_id": 161646},
    {"name": "California", "osm_id": 165475},
    {"name": "Colorado", "osm_id": 161961},
    {"name": "Connecticut", "osm_id": 165794},
    {"name": "Delaware", "osm_id": 162110},
    {"name": "Florida", "osm_id": 162050},
    {"name": "Georgia", "osm_id": 161957},
    {"name": "Hawaii", "osm_id": 166563},
    {"name": "Idaho", "osm_id": 162116},
    {"name": "Illinois", "osm_id": 122586},
    {"name": "Indiana", "osm_id": 161816},
    {"name": "Iowa", "osm_id": 161650},
    {"name": "Kansas", "osm_id": 161644},
    {"name": "Kentucky", "osm_id": 161655},
    {"name": "Louisiana", "osm_id": 224922},
    {"name": "Maine", "osm_id": 63512},
    {"name": "Maryland", "osm_id": 162112},
    {"name": "Massachusetts", "osm_id": 61315},
    {"name": "Michigan", "osm_id": 165789},
    {"name": "Minnesota", "osm_id": 165471},
    {"name": "Mississippi", "osm_id": 161943},
    {"name": "Missouri", "osm_id": 161638},
    {"name": "Montana", "osm_id": 162115},
    {"name": "Nebraska", "osm_id": 161648},
    {"name": "Nevada", "osm_id": 165473},
    {"name": "New Hampshire", "osm_id": 67213},
    {"name": "New Jersey", "osm_id": 224951},
    {"name": "New Mexico", "osm_id": 162014},
    {"name": "New York", "osm_id": 61320},
    {"name": "North Carolina", "osm_id": 224045},
    {"name": "North Dakota", "osm_id": 161653},
    {"name": "Ohio", "osm_id": 162061},
    {"name": "Oklahoma", "osm_id": 161645},
    {"name": "Oregon", "osm_id": 165476},
    {"name": "Pennsylvania", "osm_id": 162109},
    {"name": "Rhode Island", "osm_id": 392915},
    {"name": "South Carolina", "osm_id": 224040},
    {"name": "South Dakota", "osm_id": 161652},
    {"name": "Tennessee", "osm_id": 161838},
    {"name": "Texas", "osm_id": 114690},
    {"name": "Utah", "osm_id": 161993},
    {"name": "Vermont", "osm_id": 60759},
    {"name": "Virginia", "osm_id": 224042},
    {"name": "Washington", "osm_id": 165479},
    {"name": "West Virginia", "osm_id": 162068},
    {"name": "Wisconsin", "osm_id": 165466},
    {"name": "Wyoming", "osm_id": 161991},
]

# Top 20 Canadian cities by population
CA_CITIES = [
    {"name": "Toronto", "osm_id": 324211},
    {"name": "Montreal", "osm_id": 1634158},
    {"name": "Vancouver", "osm_id": 1852574},
    {"name": "Calgary", "osm_id": 3463031},
    {"name": "Edmonton", "osm_id": 2564506},
    {"name": "Ottawa", "osm_id": 4136816},
    {"name": "Winnipeg", "osm_id": 2084814},
    {"name": "Quebec City", "osm_id": 3535832},
    {"name": "Hamilton", "osm_id": 6989036},
    {"name": "Kitchener", "osm_id": 7356967},
    {"name": "London", "osm_id": 3377498},
    {"name": "Halifax", "osm_id": 2094054},
    {"name": "Victoria", "osm_id": 1688463},
    {"name": "Oshawa", "osm_id": 7978172},
    {"name": "Windsor", "osm_id": 7361845},
    {"name": "Saskatoon", "osm_id": 2725768},
    {"name": "Regina", "osm_id": 3373762},
    {"name": "St. John's", "osm_id": 2220571},
    {"name": "Kelowna", "osm_id": 2256964},
    {"name": "Barrie", "osm_id": 7932498},
]

# Etsy-optimized generation settings for provinces/states
ETSY_DEFAULTS_PROVINCE = {
    "product_type": "province",
    "board_size": "large",           # 20x24" — popular wall art size
    "style": "filled",               # Clean filled look photographs well
    "show_coordinates": True,
    "font_size_mm": 14,
    "simplification": "auto",
    "include_islands": True,
    "min_island_area_m2": 5000,
    "include_streets": False,        # Clean look, no streets for provinces
    "include_contours": False,
    "export_format": "svg",
}

# Etsy-optimized generation settings for city street maps
ETSY_DEFAULTS_CITY = {
    "product_type": "city",
    "board_size": "large",           # 20x24" — popular wall art size
    "style": "filled",               # Clean filled look
    "show_coordinates": True,
    "font_size_mm": 14,
    "simplification": "auto",
    "include_islands": True,
    "min_island_area_m2": 5000,
    "include_streets": True,         # Streets make city maps look professional
    "include_contours": False,
    "export_format": "svg",
}

# All three styles for --all-styles mode
CUT_STYLES = ["filled", "outline", "engraved"]


def build_generate_request(location: dict, style: str, board_size: str, product_type: str = "province") -> dict:
    """Build a generation API request for a province/state/city."""
    defaults = ETSY_DEFAULTS_CITY if product_type == "city" else ETSY_DEFAULTS_PROVINCE
    req = {
        **defaults,
        "osm_id": location["osm_id"],
        "osm_type": "relation",
        "text": location["name"],
        "style": style,
        "board_size": board_size,
    }
    return req


def generate_single(
    client: httpx.Client,
    base_url: str,
    token: str,
    location: dict,
    style: str,
    board_size: str,
    product_type: str = "province",
) -> dict | None:
    """Generate a single map via the API."""
    req = build_generate_request(location, style, board_size, product_type)
    headers = {"Authorization": f"Bearer {token}"}

    try:
        resp = client.post(
            f"{base_url}/api/v1/generate",
            json=req,
            headers=headers,
            timeout=120,
        )
        if resp.status_code == 200:
            return resp.json()
        else:
            print(f"  FAILED ({resp.status_code}): {resp.text[:200]}")
            return None
    except httpx.TimeoutException:
        print(f"  TIMEOUT: {location['name']}")
        return None
    except httpx.HTTPError as e:
        print(f"  ERROR: {location['name']}: {e}")
        return None


def run_catalog_generation(args):
    """Generate the full Etsy catalog."""
    # Build location groups with their product types
    groups = []  # list of (product_type, label, locations)

    gen_type = args.type

    if gen_type in ("provinces", "all"):
        if args.country in ("ca", "all"):
            groups.append(("province", "Canadian Provinces", CA_PROVINCES))
        if args.country in ("us", "all"):
            groups.append(("province", "US States", US_STATES))

    if gen_type in ("cities", "all"):
        groups.append(("city", "Canadian Cities", CA_CITIES))

    styles = CUT_STYLES if args.all_styles else [args.style]

    total_locations = sum(len(g[2]) for g in groups)
    total = total_locations * len(styles)
    print(f"\nMapForge Etsy Catalog Generator")
    print(f"================================")
    for ptype, label, locs in groups:
        print(f"  {label}: {len(locs)} ({ptype})")
    print(f"Styles: {', '.join(styles)}")
    print(f"Board size: {args.board_size}")
    print(f"Total designs: {total}")
    print(f"API: {args.base_url}")
    print()

    results = {"succeeded": [], "failed": []}
    count = 0

    with httpx.Client() as client:
        for style in styles:
            print(f"\n--- Style: {style.upper()} ---")
            for product_type, group_label, locations in groups:
                print(f"\n  [{group_label}]")
                for loc in locations:
                    count += 1
                    name = loc["name"]
                    streets_note = " +streets" if product_type == "city" else ""
                    print(f"[{count}/{total}] Generating {name} ({style}{streets_note})...", end=" ", flush=True)

                    result = generate_single(
                        client, args.base_url, args.token, loc, style, args.board_size,
                        product_type=product_type,
                    )

                    if result:
                        file_id = result.get("file_id", "?")
                        nodes = result.get("node_count", 0)
                        dims = result.get("dimensions_mm", [0, 0])
                        print(f"OK — {file_id} ({nodes} nodes, {dims[0]:.0f}x{dims[1]:.0f}mm)")
                        results["succeeded"].append({
                            "name": name,
                            "style": style,
                            "product_type": product_type,
                            "file_id": file_id,
                            "node_count": nodes,
                            "dimensions_mm": dims,
                            "dxf_available": result.get("dxf_available", False),
                            "thumbnail_available": result.get("thumbnail_available", False),
                        })
                    else:
                        results["failed"].append({"name": name, "style": style, "product_type": product_type})

                    # Brief pause — cities with streets take longer
                    pause = 3.0 if product_type == "city" else 1.5
                    time.sleep(pause)

    # Summary
    print(f"\n\n================================")
    print(f"CATALOG GENERATION COMPLETE")
    print(f"================================")
    print(f"Succeeded: {len(results['succeeded'])}/{total}")
    print(f"Failed:    {len(results['failed'])}/{total}")

    if results["failed"]:
        print(f"\nFailed locations:")
        for f in results["failed"]:
            print(f"  - {f['name']} ({f['style']})")

    # Save results manifest
    manifest_path = Path("etsy_catalog_manifest.json")
    with open(manifest_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nManifest saved to: {manifest_path}")

    # Print file IDs for marketplace listing
    if results["succeeded"]:
        print(f"\nFile IDs for marketplace listing:")
        for r in results["succeeded"]:
            print(f"  {r['name']:30s} ({r['style']:8s}) -> {r['file_id']}")

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Generate Etsy-ready map designs for all US states and Canadian provinces"
    )
    parser.add_argument(
        "--base-url", required=True,
        help="MapForge API base URL (e.g. http://localhost:8000)",
    )
    parser.add_argument(
        "--token", required=True,
        help="JWT auth token (Pro or Admin account required)",
    )
    parser.add_argument(
        "--type", choices=["provinces", "cities", "all"], default="provinces",
        help="What to generate: provinces (states+provinces), cities (Canadian cities with streets), or all (default: provinces)",
    )
    parser.add_argument(
        "--country", choices=["us", "ca", "all"], default="all",
        help="Which country for provinces/states (default: all)",
    )
    parser.add_argument(
        "--board-size", default="large",
        choices=["small", "medium", "large", "xl", "max"],
        help="Board size preset (default: large = 20x24 inches)",
    )
    parser.add_argument(
        "--style", default="filled",
        choices=["filled", "outline", "engraved"],
        help="Cut style (default: filled)",
    )
    parser.add_argument(
        "--all-styles", action="store_true",
        help="Generate all three cut styles for each location",
    )

    args = parser.parse_args()
    run_catalog_generation(args)


if __name__ == "__main__":
    main()
