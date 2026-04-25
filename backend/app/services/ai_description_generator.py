"""AI-powered Etsy listing description generator using the Claude API.

Generates unique, SEO-optimized product descriptions for each map listing,
avoiding duplicate content penalties and maximizing search visibility.

Requires: ANTHROPIC_API_KEY environment variable.
Falls back to template-based descriptions if the API is unavailable.
"""

import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"  # Fast + cheap for bulk generation

# Cost tracking
_session_stats = {"calls": 0, "input_tokens": 0, "output_tokens": 0}


def get_api_key() -> Optional[str]:
    return os.getenv("ANTHROPIC_API_KEY")


def get_session_stats() -> dict:
    """Return token usage stats for the current session."""
    return {
        **_session_stats,
        "estimated_cost_usd": round(
            (_session_stats["input_tokens"] * 0.80 / 1_000_000)
            + (_session_stats["output_tokens"] * 4.00 / 1_000_000),
            4,
        ),
    }


def _build_system_prompt() -> str:
    return """You are a copywriter for MapForge, an Etsy shop selling printable city map wall art posters (high-resolution PNG digital downloads for framing).

Rules:
- Write compelling, unique Etsy product descriptions that drive purchases
- Each description must be genuinely different — vary sentence structure, opening hooks, selling points
- Use natural language a real shopper would search for (SEO keywords woven in naturally)
- Include the location's personality, vibe, or notable traits — make the buyer feel emotionally connected to the place
- Position this as printable WALL ART — a modern, minimalist map poster for home decor
- Suggest gift occasions: housewarming, wedding, anniversary, graduation, moving away, memorial, "hometown pride"
- Mention it prints at standard frame sizes (8x10, 11x14, 16x20, 18x24, 24x36 inches)
- Note the design shows the city's streets, parks, and water in a clean minimalist style with the location name and GPS coordinates
- Mention it is an INSTANT DIGITAL DOWNLOAD — buyer receives high-resolution PNG files, no physical product is shipped
- You may briefly mention that SVG and DXF files are also included as a bonus for CNC hobbyists and laser cutters, but this is a secondary use case — do NOT lead with it
- Keep descriptions between 900-1400 characters
- Do NOT use emojis, excessive punctuation, or ALL CAPS
- Do NOT include headers/sections like "WHAT YOU GET" — write flowing prose
- Close the description with 2–3 short testimonial-style lines attributed to "buyers" (e.g. "Buyers tell us the quality is indistinguishable from the big map-art shops"). Keep them credible, not breathless; avoid fake names
- End with a subtle call to action after the testimonials"""


def _build_title_prompt() -> str:
    return """You are a copywriter for MapForge, an Etsy shop selling printable city map wall art posters.

Generate an Etsy product title. Rules:
- Maximum 140 characters (strict limit)
- Front-load the most searchable wall-art keywords
- Include: location name, "Map", "Wall Art", "Poster" or "Print", "Printable" or "Digital Download"
- Optionally include "Custom Map", "City Map Art", "Home Decor", "Housewarming Gift"
- Separate keyword clusters with em dashes (—)
- Do NOT use emojis or excessive punctuation
- Do NOT lead with "CNC" or "SVG" — this is wall art first
- Return ONLY the title text, nothing else"""


def _build_tags_prompt() -> str:
    return """You are an Etsy SEO specialist for MapForge printable city map wall art posters.

Generate exactly 13 Etsy tags. Rules:
- Each tag max 20 characters
- Focus on WALL ART and home decor buyers first
- Include location name, "city map", "map print", "wall art", "home decor", "printable art", "digital download"
- Include gift-occasion terms like "housewarming gift" or "wedding gift"
- Mix broad terms ("map poster", "city art") with specific ("Toronto map")
- You may include one or two CNC/SVG tags at the end for the hobbyist niche, but not more
- Return ONLY a comma-separated list, nothing else"""


async def generate_description(
    location_name: str,
    style: str,
    country: str = "",
    nickname: str = "",
    capital: str = "",
    province: str = "",
    is_city: bool = False,
    board_size: str = "20x24 inches",
    node_count: Optional[int] = None,
    has_streets: bool = False,
    has_water: bool = False,
    has_contours: bool = False,
) -> Optional[str]:
    """Generate a unique AI-written product description.

    Returns None if the API is unavailable (caller should fall back to template).
    """
    api_key = get_api_key()
    if not api_key:
        logger.debug("No ANTHROPIC_API_KEY set, skipping AI description")
        return None

    location_type = "city street map poster" if is_city else (
        "Canadian province map poster" if country == "Canada" else "US state map poster"
    )
    style_labels = {
        "filled": "bold filled silhouette",
        "outline": "clean outline",
        "engraved": "detailed engraved line work",
    }

    features = []
    if has_streets:
        features.append("detailed street network")
    if has_water:
        features.append("rivers, lakes, and coastlines")
    if has_contours:
        features.append("elevation contours")

    user_msg = f"""Write a unique Etsy product description for this printable city map wall art poster:

Location: {location_name}
Type: {location_type}
Country: {country}
{f'Nickname: {nickname}' if nickname else ''}
{f'Capital: {capital}' if capital else ''}
{f'Province: {province}' if province and is_city else ''}
Visual style: {style_labels.get(style, style)}
Print size: {board_size}
{f'Map detail: {node_count:,} individual elements' if node_count else ''}
{f'Features shown: {", ".join(features)}' if features else ''}

Write a fresh, unique description that leads with the wall-art / home-decor angle.
Do not use a template format."""

    return await _call_claude(
        system=_build_system_prompt(),
        user_message=user_msg,
        max_tokens=500,
        api_key=api_key,
    )


async def generate_title(
    location_name: str,
    style: str,
    country: str = "",
    is_city: bool = False,
    province: str = "",
) -> Optional[str]:
    """Generate a unique AI-written product title. Returns None if unavailable."""
    api_key = get_api_key()
    if not api_key:
        return None

    location_type = "city street map poster" if is_city else (
        "Canadian province map poster" if country == "Canada" else "US state map poster"
    )
    style_labels = {"filled": "Filled", "outline": "Outline", "engraved": "Engraved"}

    user_msg = f"""Generate an Etsy product title for:
Location: {location_name}
Type: {location_type}
{f'Province: {province}' if province and is_city else ''}
Visual style: {style_labels.get(style, style)}
Product: Printable city map wall art poster — high-resolution PNG digital download"""

    result = await _call_claude(
        system=_build_title_prompt(),
        user_message=user_msg,
        max_tokens=80,
        api_key=api_key,
    )
    if result:
        # Strip quotes and enforce 140 char limit
        result = result.strip().strip('"\'')
        return result[:140]
    return None


async def generate_tags(
    location_name: str,
    style: str,
    country: str = "",
    is_city: bool = False,
) -> Optional[str]:
    """Generate AI-optimized Etsy tags. Returns None if unavailable."""
    api_key = get_api_key()
    if not api_key:
        return None

    location_type = "city street map poster" if is_city else (
        "Canadian province map poster" if country == "Canada" else "US state map poster"
    )

    user_msg = f"""Generate 13 Etsy tags for:
Location: {location_name}
Type: {location_type}
Country: {country}
Visual style: {style}
Product: Printable city map wall art poster (high-res PNG digital download for framing). Bonus SVG/DXF included for CNC hobbyists."""

    result = await _call_claude(
        system=_build_tags_prompt(),
        user_message=user_msg,
        max_tokens=150,
        api_key=api_key,
    )
    if result:
        # Enforce: max 13 tags, each max 20 chars
        tags = [t.strip()[:20] for t in result.split(",")][:13]
        return ",".join(tags)
    return None


async def generate_full_listing(
    location_name: str,
    style: str,
    country: str = "",
    nickname: str = "",
    capital: str = "",
    province: str = "",
    is_city: bool = False,
    board_size: str = "20x24 inches",
    node_count: Optional[int] = None,
    has_streets: bool = False,
    has_water: bool = False,
    has_contours: bool = False,
) -> dict:
    """Generate title + description + tags in one call for efficiency.

    Returns dict with keys: title, description, tags (any may be None on failure).
    Falls back gracefully — caller can use template values for any None fields.
    """
    api_key = get_api_key()
    if not api_key:
        return {"title": None, "description": None, "tags": None}

    location_type = "city street map poster" if is_city else (
        "Canadian province map poster" if country == "Canada" else "US state map poster"
    )
    style_labels = {
        "filled": "bold filled silhouette",
        "outline": "clean outline",
        "engraved": "detailed engraved line work",
    }

    features = []
    if has_streets:
        features.append("detailed street network")
    if has_water:
        features.append("rivers, lakes, and coastlines")
    if has_contours:
        features.append("elevation contours")

    user_msg = f"""Generate an Etsy listing for this printable city map wall art poster. Return EXACTLY this format:

TITLE: [your title here, max 140 chars — lead with wall-art keywords]
TAGS: [13 comma-separated tags, each max 20 chars — home decor / wall art first]
DESCRIPTION: [your description here, 800-1200 chars of flowing prose — lead with the wall-art / home-decor angle]

Product details:
- Location: {location_name}
- Type: {location_type}
- Country: {country}
{f'- Nickname: {nickname}' if nickname else ''}
{f'- Capital: {capital}' if capital else ''}
{f'- Province: {province}' if province and is_city else ''}
- Visual style: {style_labels.get(style, style)}
- Print size: {board_size}
{f'- Map detail: {node_count:,} individual elements' if node_count else ''}
{f'- Features shown: {", ".join(features)}' if features else ''}
- Delivery: instant digital download (no physical product shipped)
- Primary file: high-resolution PNG ready to print at frame sizes (8x10, 11x14, 16x20, 18x24, 24x36)
- Bonus files: SVG and DXF included for CNC hobbyists and laser cutters (VCarve Pro, Fusion 360, Carbide Create, LightBurn, Easel)"""

    system = """You are a copywriter for MapForge, an Etsy shop selling printable city map wall art posters (high-resolution PNG digital downloads for framing).

Write compelling, unique listings that drive purchases. Each listing must be genuinely different.
Lead with the wall-art / home-decor angle — this is primarily framed art for the wall, not a CNC file.
Make the buyer feel emotionally connected to the location: hometown pride, a meaningful gift, a memory of a place that matters.
Mention gift occasions (housewarming, wedding, anniversary, moving away, graduation).
Note that it prints at standard frame sizes and is an instant digital download.
You may briefly mention that SVG/DXF files are also bundled for CNC hobbyists — but only as a secondary bonus, never as the lead.
Use natural SEO keywords woven into flowing prose.
Do NOT use emojis, ALL CAPS, or excessive punctuation.
Do NOT use section headers in the description — write flowing prose.
Return the EXACT format requested: TITLE, TAGS, then DESCRIPTION."""

    result = await _call_claude(
        system=system,
        user_message=user_msg,
        max_tokens=700,
        api_key=api_key,
    )

    if not result:
        return {"title": None, "description": None, "tags": None}

    return _parse_full_listing(result)


def _parse_full_listing(text: str) -> dict:
    """Parse the combined TITLE/TAGS/DESCRIPTION response."""
    title = None
    tags = None
    description = None

    lines = text.strip().split("\n")
    desc_lines = []
    in_description = False

    for line in lines:
        stripped = line.strip()
        if stripped.upper().startswith("TITLE:"):
            title = stripped[6:].strip().strip('"\'')[:140]
            in_description = False
        elif stripped.upper().startswith("TAGS:"):
            raw_tags = stripped[5:].strip()
            tags = ",".join(t.strip()[:20] for t in raw_tags.split(","))[:13]
            in_description = False
        elif stripped.upper().startswith("DESCRIPTION:"):
            desc_start = stripped[12:].strip()
            if desc_start:
                desc_lines.append(desc_start)
            in_description = True
        elif in_description:
            desc_lines.append(line)

    if desc_lines:
        description = "\n".join(desc_lines).strip()

    return {"title": title, "description": description, "tags": tags}


async def _call_claude(
    system: str,
    user_message: str,
    max_tokens: int,
    api_key: str,
) -> Optional[str]:
    """Make a single Claude API call. Returns response text or None on failure."""
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": ANTHROPIC_MODEL,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user_message}],
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                ANTHROPIC_API_URL,
                json=payload,
                headers=headers,
                timeout=30.0,
            )

        if resp.status_code != 200:
            logger.warning("Claude API error %d: %s", resp.status_code, resp.text[:200])
            return None

        data = resp.json()

        # Track usage
        usage = data.get("usage", {})
        _session_stats["calls"] += 1
        _session_stats["input_tokens"] += usage.get("input_tokens", 0)
        _session_stats["output_tokens"] += usage.get("output_tokens", 0)

        content = data.get("content", [])
        if content and content[0].get("type") == "text":
            return content[0]["text"]

        return None

    except httpx.TimeoutException:
        logger.warning("Claude API timeout for description generation")
        return None
    except Exception as e:
        logger.warning("Claude API call failed: %s", e)
        return None
