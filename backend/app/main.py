"""MapForge CNC — FastAPI Application Entry Point."""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import search, generate

app = FastAPI(
    title="MapForge CNC",
    description="Canadian Geographic SVG Generator for CNC Routing",
    version="1.0.0",
)

# Allow Railway frontend URL, localhost dev, and any custom origin via env
allowed_origins = [
    "http://localhost:3000",
    "http://localhost:5173",
]
if os.environ.get("FRONTEND_URL"):
    allowed_origins.append(os.environ["FRONTEND_URL"])
if os.environ.get("RAILWAY_PUBLIC_DOMAIN"):
    allowed_origins.append(f"https://{os.environ['RAILWAY_PUBLIC_DOMAIN']}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(search.router)
app.include_router(generate.router)


@app.get("/")
async def root():
    return {
        "app": "MapForge CNC",
        "version": "1.0.0",
        "description": "Canadian Geographic SVG Generator for CNC Routing",
        "docs": "/docs",
    }


@app.get("/health")
async def health():
    return {"status": "ok"}
