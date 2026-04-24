"""MapForge — FastAPI Application Entry Point.

MapForge is a printable city map wall art generator. The primary product is
a high-resolution PNG poster ready to print and frame. Each download also
bundles SVG and DXF vector files as a bonus for CNC hobbyists and laser
cutters (VCarve Pro, Fusion 360, Carbide Create, LightBurn, Easel).
"""

import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db, init_db
from app.logging_config import log, reset_request_id, set_request_id
from app.routers import admin, auth, etsy, generate, library, marketplace, orders, search, webhooks

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    log.info("MapForge starting up...")
    log.info(f"DATABASE_URL dialect: {settings.DATABASE_URL.split('://')[0]}")
    log.info(f"PORT: {os.environ.get('PORT', 'not set (defaulting to 8000)')}")
    if settings.MAPTILER_API_KEY:
        log.info("MAPTILER_API_KEY (env): set")
    else:
        log.info(
            "MAPTILER_API_KEY (env): not set — will read from app_settings DB "
            "row (configurable via /admin). If neither is set, coastal maps "
            "fall back to Overpass (noisy water, no ocean polygons, no parks)."
        )
    try:
        await init_db()
        log.info("Database initialized")
    except Exception as e:
        log.error(f"Database initialization failed — app will start without DB: {e}")

    # Ensure local storage directory exists
    if settings.STORAGE_BACKEND == "local":
        os.makedirs(settings.STORAGE_LOCAL_PATH, exist_ok=True)

    # Pre-fetch popular locations (non-blocking, runs in background)
    if settings.REDIS_URL:
        import asyncio
        from app.services.popular_locations import prefetch_popular_locations
        asyncio.create_task(prefetch_popular_locations(include_us=True))
        log.info("Popular locations pre-fetch started in background")

    yield
    log.info("MapForge shutting down...")


# Rate limiter
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="MapForge",
    description=(
        "Printable City Map Wall Art Generator — high-resolution PNG posters "
        "for framing, with bonus SVG/DXF files for CNC and laser cutting."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS
allowed_origins = [
    "http://localhost:3000",
    "http://localhost:5173",
]
if settings.FRONTEND_URL:
    allowed_origins.append(settings.FRONTEND_URL)
railway_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN")
if railway_domain:
    allowed_origins.append(f"https://{railway_domain}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """Tag every request with a correlation id.

    Honours an inbound `X-Request-ID` header (useful when Railway's
    edge proxy or a load balancer already stamps one) and falls back
    to a fresh UUID. The id is stashed on the logging contextvar so
    `log.info("…")` lines inside handlers carry it, and echoed back
    on the response so the client can quote it when reporting bugs.
    """
    req_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    token = set_request_id(req_id)
    request.state.request_id = req_id
    try:
        response = await call_next(request)
    finally:
        reset_request_id(token)
    response.headers["X-Request-ID"] = req_id
    return response


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """Add security headers to all responses."""
    response = await call_next(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if os.environ.get("RAILWAY_PUBLIC_DOMAIN"):
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

# API Routers
app.include_router(admin.router)
app.include_router(auth.router)
app.include_router(search.router)
app.include_router(generate.router)
app.include_router(library.router)
app.include_router(marketplace.router)
app.include_router(etsy.router)
app.include_router(orders.router)
app.include_router(webhooks.router)


@app.get("/api/v1/config")
async def get_public_config(db: AsyncSession = Depends(get_db)):
    """Public config for the frontend (no auth required).

    Exposes the MapTiler API key to the browser because MapLibre GL
    JS needs it to fetch vector tiles directly. Lock the key's
    referer / origin list at MapTiler so it only works from your
    production domain. Never reuse this key server-side.
    """
    from app.config import settings
    from app.services.app_settings import get_maptiler_key
    try:
        maptiler_key = await get_maptiler_key(db)
    except Exception:
        maptiler_key = ""
    return {
        "etsy_shop_url": settings.ETSY_SHOP_URL or None,
        "maptiler_key": maptiler_key or None,
    }


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch unhandled exceptions and return JSON instead of HTML tracebacks."""
    log.error(f"Unhandled error on {request.method} {request.url.path}: {type(exc).__name__}: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error. Please try again later."},
    )


# Serve frontend static files (built React app)
# This must come AFTER API routes so /api/* takes priority
if STATIC_DIR.is_dir() and (STATIC_DIR / "index.html").is_file():
    assets_dir = STATIC_DIR / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Serve the React SPA — all non-API routes return index.html."""
        file_path = STATIC_DIR / full_path
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(STATIC_DIR / "index.html")
else:
    log.info("No frontend build found — serving API only")

    @app.get("/")
    async def root():
        return {
            "app": "MapForge",
            "version": "1.0.0",
            "description": (
                "Printable City Map Wall Art Generator — PNG posters for "
                "framing, with bonus SVG/DXF files for CNC hobbyists."
            ),
            "docs": "/docs",
        }
