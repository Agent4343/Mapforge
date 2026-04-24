"""Shared slowapi Limiter with an XFF-aware client-IP key function.

slowapi's built-in `get_remote_address` reads `request.client.host`,
which behind Railway/NGINX/Cloudflare is the proxy IP — meaning every
request looks like it came from the same address and per-user limits
silently become one global bucket. This module derives the original
client IP from `X-Forwarded-For` (Railway strips any client-supplied
XFF before adding the real one, so the first entry is trustworthy).
"""

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address


def client_ip_key_func(request: Request) -> str:
    """Return the original client IP, honouring a proxy-set XFF header.

    Per RFC 7239 / de-facto convention, the first comma-separated entry
    in `X-Forwarded-For` is the original client. If there's no XFF
    header (local dev, non-proxied host) we fall back to the socket
    peer via slowapi's default helper.
    """
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        first = xff.split(",", 1)[0].strip()
        if first:
            return first
    return get_remote_address(request)


# Shared limiter. Routers/middleware import this rather than spinning
# up their own `Limiter(key_func=get_remote_address)` — that would use
# the proxy IP and break per-user enforcement.
limiter = Limiter(key_func=client_ip_key_func)
