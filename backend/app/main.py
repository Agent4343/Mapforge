"""MapForge CNC — FastAPI Application Entry Point."""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from app.config import settings
from app.database import init_db
from app.logging_config import log
from app.routers import admin, auth, designs, generate, library, marketplace, search, webhooks

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    log.info("MapForge CNC starting up...")
    log.info(f"DATABASE_URL dialect: {settings.DATABASE_URL.split('://')[0]}")
    log.info(f"PORT: {os.environ.get('PORT', 'not set (defaulting to 8000)')}")

    # Validate production configuration
    issues = settings.validate_production()
    for issue in issues:
        if settings.is_production:
            log.error(f"CONFIG: {issue}")
        else:
            log.warning(f"CONFIG: {issue}")

    # Ensure local storage directory exists
    if settings.STORAGE_BACKEND == "local":
        os.makedirs(settings.STORAGE_LOCAL_PATH, exist_ok=True)

    # Database initialization — run in background so the app starts immediately
    # and Railway's healthcheck can reach the server while DB connects.
    import asyncio

    async def _background_init():
        try:
            await init_db()
            log.info("Database initialized")
        except Exception as e:
            log.error(f"Database initialization failed: {e}")
            log.warning("Running without database — /health will report degraded status")

        # Pre-fetch popular locations after DB is ready
        if settings.REDIS_URL:
            from app.services.popular_locations import prefetch_popular_locations
            asyncio.create_task(prefetch_popular_locations(include_us=True))
            log.info("Popular locations pre-fetch started in background")

    asyncio.create_task(_background_init())

    yield
    log.info("MapForge CNC shutting down...")


# Rate limiter
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="MapForge CNC",
    description="Geographic SVG Generator for CNC Routing — Canada, US, and Global",
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
async def add_security_headers(request: Request, call_next):
    """Add security headers to all responses."""
    response = await call_next(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # Prevent browsers from caching HTML pages so new deploys are picked up
    if request.url.path == "/" or not request.url.path.startswith(("/api", "/assets")):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response

# API Routers
app.include_router(admin.router)
app.include_router(auth.router)
app.include_router(designs.router)
app.include_router(search.router)
app.include_router(generate.router)
app.include_router(library.router)
app.include_router(marketplace.router)
app.include_router(webhooks.router)


@app.get("/health")
async def health():
    """Health check — verifies database connectivity."""
    from sqlalchemy import text
    from app.database import async_session

    try:
        async with async_session() as db:
            await db.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except Exception as e:
        log.error(f"Health check DB failure: {e}")
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "database": "disconnected"},
        )


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
            "app": "MapForge CNC",
            "version": "1.0.0",
            "description": "Canadian Geographic SVG Generator for CNC Routing",
            "docs": "/docs",
        }
