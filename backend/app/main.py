"""MapForge CNC — FastAPI Application Entry Point."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import search, generate

app = FastAPI(
    title="MapForge CNC",
    description="Canadian Geographic SVG Generator for CNC Routing",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
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
