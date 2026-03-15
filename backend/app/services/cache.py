"""Optional Redis caching layer for search and geometry queries.

Falls back gracefully when Redis is not configured.
"""

import json
from typing import Any

from app.config import settings
from app.logging_config import log

_redis_client = None
_redis_available = False


async def _get_redis():
    """Lazy-initialize Redis connection."""
    global _redis_client, _redis_available

    if _redis_client is not None:
        return _redis_client

    if not settings.REDIS_URL:
        _redis_available = False
        return None

    try:
        import redis.asyncio as aioredis
        _redis_client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            socket_timeout=2,
            socket_connect_timeout=2,
        )
        await _redis_client.ping()
        _redis_available = True
        log.info("Redis cache connected")
        return _redis_client
    except Exception as e:
        log.warning(f"Redis not available, caching disabled: {e}")
        _redis_available = False
        _redis_client = None
        return None


async def cache_get(key: str) -> Any | None:
    """Get a value from cache. Returns None on miss or if Redis unavailable."""
    try:
        client = await _get_redis()
        if client is None:
            return None
        val = await client.get(key)
        if val is not None:
            return json.loads(val)
    except Exception as e:
        log.debug(f"Cache get error for {key}: {e}")
    return None


async def cache_set(key: str, value: Any, ttl: int | None = None) -> bool:
    """Set a value in cache. Returns True on success."""
    try:
        client = await _get_redis()
        if client is None:
            return False
        serialized = json.dumps(value, default=str)
        if ttl:
            await client.setex(key, ttl, serialized)
        else:
            await client.set(key, serialized)
        return True
    except Exception as e:
        log.debug(f"Cache set error for {key}: {e}")
        return False


async def cache_delete(key: str) -> bool:
    """Delete a key from cache."""
    try:
        client = await _get_redis()
        if client is None:
            return False
        await client.delete(key)
        return True
    except Exception:
        return False


def make_search_key(query: str, country: str, limit: int) -> str:
    """Generate a cache key for search queries."""
    return f"search:{country}:{limit}:{query.lower().strip()}"


def make_geometry_key(osm_id: int, osm_type: str) -> str:
    """Generate a cache key for geometry data."""
    return f"geom:{osm_type}:{osm_id}"
