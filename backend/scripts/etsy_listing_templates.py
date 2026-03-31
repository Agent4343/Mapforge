#!/usr/bin/env python3
"""Etsy listing templates for MapForge province/state maps.

Generates optimized titles, descriptions, and tags for each state/province
to maximize Etsy search visibility and conversion.

Usage:
    # Create marketplace listings from generated catalog:
    python scripts/etsy_listing_templates.py --base-url http://localhost:8000 --token YOUR_JWT --manifest etsy_catalog_manifest.json

    # Preview templates without creating listings:
    python scripts/etsy_listing_templates.py --preview --country us

    # Export CSV for manual Etsy upload:
    python scripts/etsy_listing_templates.py --export-csv etsy_listings.csv --manifest etsy_catalog_manifest.json
"""

import argparse
import asyncio
import csv
import json
import sys
from pathlib import Path

import httpx

# Add backend to path for AI service import
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.services.ai_description_generator import (
    generate_full_listing as ai_generate_full_listing,
    get_session_stats,
)

# Style display names for listings
STYLE_NAMES = {
    "filled": "Filled",
    "outline": "Outline",
    "engraved": "Engraved",
}

STYLE_DESCRIPTIONS = {
    "filled": "pocket-carved with a clean filled silhouette",
    "outline": "profile-cut with a precise outline border",
    "engraved": "v-carved with detailed engraved lines",
}

# State/province metadata for rich descriptions
LOCATION_META = {
    # Canadian Provinces
    "Ontario": {"capital": "Toronto", "nickname": "The Heartland Province", "country": "Canada"},
    "Quebec": {"capital": "Quebec City", "nickname": "La Belle Province", "country": "Canada"},
    "British Columbia": {"capital": "Victoria", "nickname": "The Pacific Province", "country": "Canada"},
    "Alberta": {"capital": "Edmonton", "nickname": "Wild Rose Country", "country": "Canada"},
    "Manitoba": {"capital": "Winnipeg", "nickname": "The Keystone Province", "country": "Canada"},
    "Saskatchewan": {"capital": "Regina", "nickname": "Land of Living Skies", "country": "Canada"},
    "Nova Scotia": {"capital": "Halifax", "nickname": "Canada's Ocean Playground", "country": "Canada"},
    "New Brunswick": {"capital": "Fredericton", "nickname": "The Picture Province", "country": "Canada"},
    "Prince Edward Island": {"capital": "Charlottetown", "nickname": "The Birthplace of Confederation", "country": "Canada"},
    "Newfoundland and Labrador": {"capital": "St. John's", "nickname": "The Rock", "country": "Canada"},
    "Northwest Territories": {"capital": "Yellowknife", "nickname": "The Northern Frontier", "country": "Canada"},
    "Yukon": {"capital": "Whitehorse", "nickname": "Canada's True North", "country": "Canada"},
    "Nunavut": {"capital": "Iqaluit", "nickname": "Our Land", "country": "Canada"},
    # US States
    "Alabama": {"capital": "Montgomery", "nickname": "The Heart of Dixie", "country": "USA"},
    "Alaska": {"capital": "Juneau", "nickname": "The Last Frontier", "country": "USA"},
    "Arizona": {"capital": "Phoenix", "nickname": "The Grand Canyon State", "country": "USA"},
    "Arkansas": {"capital": "Little Rock", "nickname": "The Natural State", "country": "USA"},
    "California": {"capital": "Sacramento", "nickname": "The Golden State", "country": "USA"},
    "Colorado": {"capital": "Denver", "nickname": "The Centennial State", "country": "USA"},
    "Connecticut": {"capital": "Hartford", "nickname": "The Constitution State", "country": "USA"},
    "Delaware": {"capital": "Dover", "nickname": "The First State", "country": "USA"},
    "Florida": {"capital": "Tallahassee", "nickname": "The Sunshine State", "country": "USA"},
    "Georgia": {"capital": "Atlanta", "nickname": "The Peach State", "country": "USA"},
    "Hawaii": {"capital": "Honolulu", "nickname": "The Aloha State", "country": "USA"},
    "Idaho": {"capital": "Boise", "nickname": "The Gem State", "country": "USA"},
    "Illinois": {"capital": "Springfield", "nickname": "The Prairie State", "country": "USA"},
    "Indiana": {"capital": "Indianapolis", "nickname": "The Hoosier State", "country": "USA"},
    "Iowa": {"capital": "Des Moines", "nickname": "The Hawkeye State", "country": "USA"},
    "Kansas": {"capital": "Topeka", "nickname": "The Sunflower State", "country": "USA"},
    "Kentucky": {"capital": "Frankfort", "nickname": "The Bluegrass State", "country": "USA"},
    "Louisiana": {"capital": "Baton Rouge", "nickname": "The Pelican State", "country": "USA"},
    "Maine": {"capital": "Augusta", "nickname": "The Pine Tree State", "country": "USA"},
    "Maryland": {"capital": "Annapolis", "nickname": "The Old Line State", "country": "USA"},
    "Massachusetts": {"capital": "Boston", "nickname": "The Bay State", "country": "USA"},
    "Michigan": {"capital": "Lansing", "nickname": "The Great Lakes State", "country": "USA"},
    "Minnesota": {"capital": "Saint Paul", "nickname": "The North Star State", "country": "USA"},
    "Mississippi": {"capital": "Jackson", "nickname": "The Magnolia State", "country": "USA"},
    "Missouri": {"capital": "Jefferson City", "nickname": "The Show-Me State", "country": "USA"},
    "Montana": {"capital": "Helena", "nickname": "Big Sky Country", "country": "USA"},
    "Nebraska": {"capital": "Lincoln", "nickname": "The Cornhusker State", "country": "USA"},
    "Nevada": {"capital": "Carson City", "nickname": "The Silver State", "country": "USA"},
    "New Hampshire": {"capital": "Concord", "nickname": "The Granite State", "country": "USA"},
    "New Jersey": {"capital": "Trenton", "nickname": "The Garden State", "country": "USA"},
    "New Mexico": {"capital": "Santa Fe", "nickname": "The Land of Enchantment", "country": "USA"},
    "New York": {"capital": "Albany", "nickname": "The Empire State", "country": "USA"},
    "North Carolina": {"capital": "Raleigh", "nickname": "The Tar Heel State", "country": "USA"},
    "North Dakota": {"capital": "Bismarck", "nickname": "The Peace Garden State", "country": "USA"},
    "Ohio": {"capital": "Columbus", "nickname": "The Buckeye State", "country": "USA"},
    "Oklahoma": {"capital": "Oklahoma City", "nickname": "The Sooner State", "country": "USA"},
    "Oregon": {"capital": "Salem", "nickname": "The Beaver State", "country": "USA"},
    "Pennsylvania": {"capital": "Harrisburg", "nickname": "The Keystone State", "country": "USA"},
    "Rhode Island": {"capital": "Providence", "nickname": "The Ocean State", "country": "USA"},
    "South Carolina": {"capital": "Columbia", "nickname": "The Palmetto State", "country": "USA"},
    "South Dakota": {"capital": "Pierre", "nickname": "The Mount Rushmore State", "country": "USA"},
    "Tennessee": {"capital": "Nashville", "nickname": "The Volunteer State", "country": "USA"},
    "Texas": {"capital": "Austin", "nickname": "The Lone Star State", "country": "USA"},
    "Utah": {"capital": "Salt Lake City", "nickname": "The Beehive State", "country": "USA"},
    "Vermont": {"capital": "Montpelier", "nickname": "The Green Mountain State", "country": "USA"},
    "Virginia": {"capital": "Richmond", "nickname": "The Old Dominion", "country": "USA"},
    "Washington": {"capital": "Olympia", "nickname": "The Evergreen State", "country": "USA"},
    "West Virginia": {"capital": "Charleston", "nickname": "The Mountain State", "country": "USA"},
    "Wisconsin": {"capital": "Madison", "nickname": "The Badger State", "country": "USA"},
    "Wyoming": {"capital": "Cheyenne", "nickname": "The Cowboy State", "country": "USA"},
    # Canadian Cities
    "Toronto": {"province": "Ontario", "nickname": "The Six", "country": "Canada", "type": "city"},
    "Montreal": {"province": "Quebec", "nickname": "The City of Saints", "country": "Canada", "type": "city"},
    "Vancouver": {"province": "British Columbia", "nickname": "Hollywood North", "country": "Canada", "type": "city"},
    "Calgary": {"province": "Alberta", "nickname": "Cowtown", "country": "Canada", "type": "city"},
    "Edmonton": {"province": "Alberta", "nickname": "City of Champions", "country": "Canada", "type": "city"},
    "Ottawa": {"province": "Ontario", "nickname": "The Capital", "country": "Canada", "type": "city"},
    "Winnipeg": {"province": "Manitoba", "nickname": "The Peg", "country": "Canada", "type": "city"},
    "Quebec City": {"province": "Quebec", "nickname": "La Vieille Capitale", "country": "Canada", "type": "city"},
    "Hamilton": {"province": "Ontario", "nickname": "The Hammer", "country": "Canada", "type": "city"},
    "Kitchener": {"province": "Ontario", "nickname": "K-W", "country": "Canada", "type": "city"},
    "London": {"province": "Ontario", "nickname": "The Forest City", "country": "Canada", "type": "city"},
    "Halifax": {"province": "Nova Scotia", "nickname": "The Halifax", "country": "Canada", "type": "city"},
    "Victoria": {"province": "British Columbia", "nickname": "The Garden City", "country": "Canada", "type": "city"},
    "Oshawa": {"province": "Ontario", "nickname": "The Dirty Shwa", "country": "Canada", "type": "city"},
    "Windsor": {"province": "Ontario", "nickname": "The City of Roses", "country": "Canada", "type": "city"},
    "Saskatoon": {"province": "Saskatchewan", "nickname": "Paris of the Prairies", "country": "Canada", "type": "city"},
    "Regina": {"province": "Saskatchewan", "nickname": "Queen City", "country": "Canada", "type": "city"},
    "St. John's": {"province": "Newfoundland and Labrador", "nickname": "The Oldest City", "country": "Canada", "type": "city"},
    "Kelowna": {"province": "British Columbia", "nickname": "The Orchard City", "country": "Canada", "type": "city"},
    "Barrie": {"province": "Ontario", "nickname": "Gateway to Cottage Country", "country": "Canada", "type": "city"},
}


def generate_title(name: str, style: str) -> str:
    """Generate an Etsy-optimized title (max 140 chars)."""
    meta = LOCATION_META.get(name, {})
    country = meta.get("country", "")
    is_city = meta.get("type") == "city"
    style_label = STYLE_NAMES.get(style, style.title())

    if is_city:
        province = meta.get("province", "Canada")
        title = f"{name} City Street Map Print — {style_label} — {province} Wall Art — Digital Download"
    elif country == "Canada":
        title = f"{name} Map Print — {style_label} Style — Canadian Province Wall Art — Digital Download"
    else:
        title = f"{name} State Map Print — {style_label} Style — Wall Art Decor — Digital Download"

    # Etsy title limit is 140 characters
    if len(title) > 140:
        if is_city:
            title = f"{name} Street Map Print — {style_label} — City Wall Art"
        elif country == "Canada":
            title = f"{name} Map Print — {style_label} — Canadian Province Art"
        else:
            title = f"{name} Map Print — {style_label} — State Wall Art"

    return title[:140]


def generate_description(name: str, style: str) -> str:
    """Generate a rich Etsy product description."""
    meta = LOCATION_META.get(name, {})
    country = meta.get("country", "")
    nickname = meta.get("nickname", "")
    is_city = meta.get("type") == "city"
    style_desc = STYLE_DESCRIPTIONS.get(style, style)

    if is_city:
        province = meta.get("province", "Canada")
        product_label = f"city street map of {name}, {province}"
        streets_section = """
STREET MAP LAYERS:
- detail_lines — Major and minor road network (engrave: 1/8" ball nose)
- street_labels — Road names placed along paths (V-carve: 60° V-bit)
- water_features — Rivers, lakes, and coastlines (pocket: 1/8" ball nose)
"""
        perfect_for = f"""PERFECT FOR:
- Wall art and home decor
- City pride gifts for {name} locals
- Housewarming gifts for someone moving to {name}
- Real estate closing gifts
- Wedding venue maps
- {name}, {province} hometown pride
- Framed prints and poster displays"""
    else:
        product_label = f"{'Canadian province' if country == 'Canada' else 'US state'} map of {name}"
        streets_section = ""
        perfect_for = f"""PERFECT FOR:
- Wall art and home decor
- Framed prints and poster displays
- {name} pride gifts and home decor
- Housewarming, birthday, and holiday gifts"""

    desc = f"""{name} — {nickname}

A beautifully designed {product_label} — perfect as wall art, a framed print, or a personalized gift.

WHAT YOU GET:
- High-resolution PNG print file (print-ready quality)
- Clean, professional map design
- Geographic coordinates displayed on design
- Instant digital download

DESIGN DETAILS:
- Product type: {product_label}
- Style: {STYLE_NAMES.get(style, style.title())}
- Print-ready resolution for large format printing

LAYER STRUCTURE (for VCarve / toolpath mapping):
- board_outline — Optional profile cut (1/4" downcut endmill)
- geography_{style} — Main map shape
- text_primary — "{name}" location text (V-carve: 60° V-bit)
- text_coordinates — Lat/lon coordinates
{streets_section}
{perfect_for}

PRINTING TIPS:
- Print at home or use a professional print service
- Looks great on matte or lustre photo paper
- Standard frame sizes available at most stores

NOTES:
- This is a DIGITAL FILE — no physical product will be shipped
- Geographic data sourced from OpenStreetMap (ODbL license)
- File can be scaled to any board size in your CAM software
- Custom markers (Home, Cottage) available — contact us"""

    return desc


def generate_tags(name: str, style: str) -> str:
    """Generate Etsy tags (max 13 tags, max 20 chars each)."""
    meta = LOCATION_META.get(name, {})
    country = meta.get("country", "")
    is_city = meta.get("type") == "city"

    # Base tags (always included)
    tags = [
        f"{name} map",
        "map print",
        "custom map",
        "wall art",
        f"{name} art",
        "city map poster",
        "map poster",
        "digital download",
        "home decor",
    ]

    if is_city:
        province = meta.get("province", "")
        tags.extend([
            "city map",
            "street map",
            f"{name} Canada",
            province[:20] if province else "Canada map",
        ])
    elif country == "Canada":
        tags.extend([
            "Canada map",
            "Canadian art",
            "province map",
            f"{name} Canada",
        ])
    else:
        tags.extend([
            "state map",
            "USA map",
            f"{name} state",
            "home state",
        ])

    # Style-specific tag
    style_tag = f"{style} style"
    tags.append(style_tag)

    # Etsy allows max 13 tags, each max 20 characters
    tags = [t[:20] for t in tags[:13]]
    return ",".join(tags)


def generate_price_cents(name: str, style: str) -> int:
    """Set price based on complexity. All prices in cents."""
    meta = LOCATION_META.get(name, {})
    is_city = meta.get("type") == "city"

    # City street maps are more detailed — premium pricing
    if is_city:
        major_cities = {"Toronto", "Montreal", "Vancouver", "Calgary", "Ottawa", "Edmonton"}
        if name in major_cities:
            return 1999  # $19.99 — major metro with tons of streets
        return 1499  # $14.99 — smaller cities

    # Large/complex states and provinces get premium pricing
    premium = {
        "Alaska", "California", "Texas", "Florida", "Michigan", "Hawaii",
        "British Columbia", "Ontario", "Quebec", "Newfoundland and Labrador",
        "Nunavut", "Northwest Territories",
    }
    if name in premium:
        return 1499  # $14.99
    return 999  # $9.99


async def ai_listing_payload(name: str, style: str, file_id: str) -> dict:
    """Build a listing payload using AI-generated content with template fallback."""
    meta = LOCATION_META.get(name, {})
    country = meta.get("country", "")
    nickname = meta.get("nickname", "")
    capital = meta.get("capital", "")
    province = meta.get("province", "")
    is_city = meta.get("type") == "city"

    ai_result = await ai_generate_full_listing(
        location_name=name,
        style=style,
        country=country,
        nickname=nickname,
        capital=capital,
        province=province,
        is_city=is_city,
        has_streets=is_city,
    )

    return {
        "file_id": file_id,
        "title": ai_result.get("title") or generate_title(name, style),
        "description": ai_result.get("description") or generate_description(name, style),
        "tags": ai_result.get("tags") or generate_tags(name, style),
        "price_cents": generate_price_cents(name, style),
    }


def create_listing_payload(name: str, style: str, file_id: str) -> dict:
    """Build a marketplace listing API request (template-based)."""
    return {
        "file_id": file_id,
        "title": generate_title(name, style),
        "description": generate_description(name, style),
        "tags": generate_tags(name, style),
        "price_cents": generate_price_cents(name, style),
    }


def preview_templates(country: str):
    """Print template previews without creating listings."""
    locations = []
    if country in ("ca", "all"):
        locations.extend([(name, "Canada") for name in [
            "Ontario", "Quebec", "British Columbia", "Alberta", "Manitoba",
            "Saskatchewan", "Nova Scotia", "New Brunswick", "Prince Edward Island",
            "Newfoundland and Labrador", "Northwest Territories", "Yukon", "Nunavut",
        ]])
    if country in ("us", "all"):
        locations.extend([(name, "USA") for name in LOCATION_META if LOCATION_META[name]["country"] == "USA"])

    for name, _ in locations:
        for style in ["filled"]:  # Preview one style
            print(f"\n{'='*70}")
            print(f"TITLE: {generate_title(name, style)}")
            print(f"PRICE: ${generate_price_cents(name, style)/100:.2f}")
            print(f"TAGS:  {generate_tags(name, style)}")
            print(f"{'='*70}")
            print(generate_description(name, style)[:500] + "...")
            print()


def export_csv(manifest_path: str, output_path: str, use_ai: bool = False):
    """Export listings as CSV for manual Etsy upload."""
    with open(manifest_path) as f:
        manifest = json.load(f)

    items = manifest.get("succeeded", [])

    if use_ai:
        rows = asyncio.run(_export_csv_ai(items))
    else:
        rows = _export_csv_template(items)

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys() if rows else [])
        writer.writeheader()
        writer.writerows(rows)

    print(f"Exported {len(rows)} listings to {output_path}")

    if use_ai:
        stats = get_session_stats()
        print(f"AI stats: {stats['calls']} API calls, ~${stats['estimated_cost_usd']:.4f} total cost")


def _export_csv_template(items: list) -> list:
    """Generate CSV rows using templates."""
    rows = []
    for item in items:
        name = item["name"]
        style = item["style"]
        file_id = item["file_id"]
        rows.append({
            "file_id": file_id,
            "name": name,
            "style": style,
            "title": generate_title(name, style),
            "description": generate_description(name, style),
            "tags": generate_tags(name, style),
            "price": f"{generate_price_cents(name, style)/100:.2f}",
            "node_count": item.get("node_count", ""),
            "dimensions_mm": f"{item.get('dimensions_mm', [0,0])[0]:.0f}x{item.get('dimensions_mm', [0,0])[1]:.0f}",
            "dxf_available": item.get("dxf_available", False),
            "thumbnail_available": item.get("thumbnail_available", False),
        })
    return rows


async def _export_csv_ai(items: list) -> list:
    """Generate CSV rows using AI descriptions."""
    rows = []
    total = len(items)
    for i, item in enumerate(items, 1):
        name = item["name"]
        style = item["style"]
        file_id = item["file_id"]

        print(f"  [{i}/{total}] Generating AI listing for {name} ({style})...", flush=True)
        payload = await ai_listing_payload(name, style, file_id)

        rows.append({
            "file_id": file_id,
            "name": name,
            "style": style,
            "title": payload["title"],
            "description": payload["description"],
            "tags": payload["tags"],
            "price": f"{payload['price_cents']/100:.2f}",
            "node_count": item.get("node_count", ""),
            "dimensions_mm": f"{item.get('dimensions_mm', [0,0])[0]:.0f}x{item.get('dimensions_mm', [0,0])[1]:.0f}",
            "dxf_available": item.get("dxf_available", False),
            "thumbnail_available": item.get("thumbnail_available", False),
        })

        # Rate limit: ~1 request/second to stay well within API limits
        await asyncio.sleep(1.0)

    return rows


def create_marketplace_listings(base_url: str, token: str, manifest_path: str, use_ai: bool = False):
    """Create marketplace listings from a generation manifest."""
    with open(manifest_path) as f:
        manifest = json.load(f)

    if use_ai:
        asyncio.run(_create_listings_ai(base_url, token, manifest))
    else:
        _create_listings_template(base_url, token, manifest)


def _create_listings_template(base_url: str, token: str, manifest: dict):
    """Create listings using template descriptions."""
    headers = {"Authorization": f"Bearer {token}"}
    succeeded = 0
    failed = 0

    with httpx.Client() as client:
        for item in manifest.get("succeeded", []):
            name = item["name"]
            style = item["style"]
            file_id = item["file_id"]

            payload = create_listing_payload(name, style, file_id)
            print(f"Listing {name} ({style})...", end=" ", flush=True)

            try:
                resp = client.post(
                    f"{base_url}/api/v1/marketplace/listings",
                    json=payload,
                    headers=headers,
                    timeout=30,
                )
                if resp.status_code in (200, 201):
                    listing_id = resp.json().get("id", "?")
                    print(f"OK — listing {listing_id}")
                    succeeded += 1
                else:
                    print(f"FAILED ({resp.status_code}): {resp.text[:200]}")
                    failed += 1
            except Exception as e:
                print(f"ERROR: {e}")
                failed += 1

            import time
            time.sleep(0.5)

    print(f"\nListings created: {succeeded}, Failed: {failed}")


async def _create_listings_ai(base_url: str, token: str, manifest: dict):
    """Create listings using AI-generated descriptions."""
    headers = {"Authorization": f"Bearer {token}"}
    succeeded = 0
    failed = 0
    items = manifest.get("succeeded", [])
    total = len(items)

    async with httpx.AsyncClient() as client:
        for i, item in enumerate(items, 1):
            name = item["name"]
            style = item["style"]
            file_id = item["file_id"]

            print(f"[{i}/{total}] AI listing for {name} ({style})...", end=" ", flush=True)

            payload = await ai_listing_payload(name, style, file_id)

            try:
                resp = await client.post(
                    f"{base_url}/api/v1/marketplace/listings",
                    json=payload,
                    headers=headers,
                    timeout=30,
                )
                if resp.status_code in (200, 201):
                    listing_id = resp.json().get("id", "?")
                    print(f"OK — listing {listing_id}")
                    succeeded += 1
                else:
                    print(f"FAILED ({resp.status_code}): {resp.text[:200]}")
                    failed += 1
            except Exception as e:
                print(f"ERROR: {e}")
                failed += 1

            await asyncio.sleep(1.0)  # Rate limit AI calls

    stats = get_session_stats()
    print(f"\nListings created: {succeeded}, Failed: {failed}")
    print(f"AI stats: {stats['calls']} API calls, ~${stats['estimated_cost_usd']:.4f} total cost")


def main():
    parser = argparse.ArgumentParser(
        description="Etsy listing templates for MapForge province/state maps"
    )
    parser.add_argument("--preview", action="store_true", help="Preview templates without creating listings")
    parser.add_argument("--country", choices=["us", "ca", "all"], default="all")
    parser.add_argument("--export-csv", metavar="PATH", help="Export listings as CSV")
    parser.add_argument("--manifest", metavar="PATH", help="Path to etsy_catalog_manifest.json")
    parser.add_argument("--base-url", help="MapForge API base URL")
    parser.add_argument("--token", help="JWT auth token")
    parser.add_argument("--create-listings", action="store_true", help="Create marketplace listings from manifest")
    parser.add_argument(
        "--ai", action="store_true",
        help="Use Claude AI to generate unique descriptions (requires ANTHROPIC_API_KEY env var)"
    )

    args = parser.parse_args()

    if args.ai:
        import os
        if not os.getenv("ANTHROPIC_API_KEY"):
            print("Error: ANTHROPIC_API_KEY environment variable required for --ai mode")
            print("  export ANTHROPIC_API_KEY=sk-ant-...")
            sys.exit(1)
        print("AI mode enabled — generating unique descriptions via Claude API")

    if args.preview:
        if args.ai:
            asyncio.run(_preview_ai(args.country))
        else:
            preview_templates(args.country)
    elif args.export_csv:
        if not args.manifest:
            print("Error: --manifest required for CSV export")
            sys.exit(1)
        export_csv(args.manifest, args.export_csv, use_ai=args.ai)
    elif args.create_listings:
        if not all([args.base_url, args.token, args.manifest]):
            print("Error: --base-url, --token, and --manifest required")
            sys.exit(1)
        create_marketplace_listings(args.base_url, args.token, args.manifest, use_ai=args.ai)
    else:
        parser.print_help()


async def _preview_ai(country: str):
    """Preview AI-generated listings for a few sample locations."""
    samples = []
    if country in ("ca", "all"):
        samples.extend(["Ontario", "Toronto", "British Columbia"])
    if country in ("us", "all"):
        samples.extend(["Texas", "California", "New York"])

    for name in samples:
        meta = LOCATION_META.get(name, {})
        style = "filled"
        print(f"\n{'='*70}")
        print(f"AI-GENERATED LISTING: {name}")
        print(f"{'='*70}")

        payload = await ai_listing_payload(name, style, "preview-id")
        print(f"TITLE: {payload['title']}")
        print(f"PRICE: ${payload['price_cents']/100:.2f}")
        print(f"TAGS:  {payload['tags']}")
        print(f"\n{payload['description']}")
        print()

    stats = get_session_stats()
    print(f"\nAI stats: {stats['calls']} API calls, ~${stats['estimated_cost_usd']:.4f} total cost")


if __name__ == "__main__":
    main()
