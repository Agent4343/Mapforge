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
    return """You are a copywriter for MapForge, an Etsy shop selling digital CNC map files (SVG/DXF).

Rules:
- Write compelling, unique Etsy product descriptions that drive purchases
- Each description must be genuinely different — vary sentence structure, opening hooks, selling points
- Use natural language a real shopper would search for (SEO keywords woven in naturally)
- Include the location's personality, vibe, or notable traits — make the buyer feel connected
- Mention the file formats (SVG, DXF, PNG) and that it's a digital download
- Keep descriptions between 800-1200 characters
- Do NOT use emojis, excessive punctuation, or ALL CAPS
- Do NOT include headers/sections like "WHAT YOU GET" — write flowing prose
- End with a subtle call to action
- Mention CNC router compatibility (VCarve Pro, Fusion 360, Carbide Create, LightBurn)
- Note it works on wood, acrylic, plywood, MDF
- This is a DIGITAL FILE — no physical product shipped"""


def _build_title_prompt() -> str:
    return """You are a copywriter for MapForge, an Etsy shop selling digital CNC map files.

Generate an Etsy product title. Rules:
- Maximum 140 characters (strict limit)
- Front-load the most searchable keywords
- Include: location name, "Map", "SVG", "DXF", file purpose
- Include cut style name if provided
- Separate keyword clusters with em dashes (—)
- Do NOT use emojis or excessive punctuation
- Return ONLY the title text, nothing else"""


def _build_tags_prompt() -> str:
    return """You are an Etsy SEO specialist for MapForge CNC map files.

Generate exactly 13 Etsy tags. Rules:
- Each tag max 20 characters
- Include location name, map type, file format, use cases
- Mix broad terms ("CNC file", "wall art") with specific ("Ontario map")
- Think about what a CNC hobbyist would search for
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

    location_type = "city street map" if is_city else (
        "Canadian province map" if country == "Canada" else "US state map"
    )
    style_labels = {
        "filled": "filled/pocket-carved silhouette",
        "outline": "outline/profile-cut border",
        "engraved": "engraved/v-carved detail lines",
    }

    features = []
    if has_streets:
        features.append("detailed street network")
    if has_water:
        features.append("lakes and rivers")
    if has_contours:
        features.append("elevation contours")

    user_msg = f"""Write a unique Etsy product description for this CNC map file:

Location: {location_name}
Type: {location_type}
Country: {country}
{f'Nickname: {nickname}' if nickname else ''}
{f'Capital: {capital}' if capital else ''}
{f'Province: {province}' if province and is_city else ''}
Cut style: {style_labels.get(style, style)}
Board size: {board_size}
{f'Geometric complexity: {node_count:,} nodes' if node_count else ''}
{f'Includes: {", ".join(features)}' if features else ''}

Write a fresh, unique description. Do not use a template format."""

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

    location_type = "city street map" if is_city else (
        "Canadian province" if country == "Canada" else "US state"
    )
    style_labels = {"filled": "Filled", "outline": "Outline", "engraved": "Engraved"}

    user_msg = f"""Generate an Etsy product title for:
Location: {location_name}
Type: {location_type}
{f'Province: {province}' if province and is_city else ''}
Cut style: {style_labels.get(style, style)}
Product: CNC-ready digital map file (SVG/DXF)"""

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

    location_type = "city street map" if is_city else (
        "Canadian province" if country == "Canada" else "US state"
    )

    user_msg = f"""Generate 13 Etsy tags for:
Location: {location_name}
Type: {location_type}
Country: {country}
Cut style: {style}
Product: CNC digital map file (SVG/DXF) for wood carving, laser cutting"""

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

    location_type = "city street map" if is_city else (
        "Canadian province map" if country == "Canada" else "US state map"
    )
    style_labels = {
        "filled": "filled/pocket-carved",
        "outline": "outline/profile-cut",
        "engraved": "engraved/v-carved",
    }

    features = []
    if has_streets:
        features.append("detailed street network")
    if has_water:
        features.append("lakes and rivers")
    if has_contours:
        features.append("elevation contours")

    user_msg = f"""Generate an Etsy listing for this CNC map file. Return EXACTLY this format:

TITLE: [your title here, max 140 chars]
TAGS: [13 comma-separated tags, each max 20 chars]
DESCRIPTION: [your description here, 800-1200 chars of flowing prose]

Product details:
- Location: {location_name}
- Type: {location_type}
- Country: {country}
{f'- Nickname: {nickname}' if nickname else ''}
{f'- Capital: {capital}' if capital else ''}
{f'- Province: {province}' if province and is_city else ''}
- Cut style: {style_labels.get(style, style)}
- Board size: {board_size}
{f'- Complexity: {node_count:,} nodes' if node_count else ''}
{f'- Features: {", ".join(features)}' if features else ''}
- Formats: SVG, DXF, PNG (digital download only)
- Compatible with: VCarve Pro, Fusion 360, Carbide Create, LightBurn, Easel"""

    system = """You are a copywriter for MapForge, an Etsy shop selling digital CNC map files (SVG/DXF).

Write compelling, unique listings that drive purchases. Each listing must be genuinely different.
Use natural SEO keywords woven into flowing prose. Make the buyer feel connected to the location.
Mention file formats, CNC compatibility, and that it's a digital download.
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
            logger.error(
                "Claude API error %d: %s (key=%s...)",
                resp.status_code,
                resp.text[:300],
                api_key[:8] if api_key else "NONE",
            )
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
        logger.error("Claude API timeout for description generation")
        return None
    except Exception as e:
        logger.error("Claude API call failed: %s: %s", type(e).__name__, e)
        return None
