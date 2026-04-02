"""Async high-resolution render job pipeline for professional print exports.

This service is intentionally engine-oriented: it keeps today's SVG->PNG/PDF
implementation, while exposing a stable interface for future MapLibre/Mapbox +
PostGIS/Turf powered rendering backends.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.logging_config import log
from app.services.file_storage import store_file
from app.services.maptiler_renderer import render_maptiler_print_png, render_png_bytes_to_pdf
from app.services.thumbnail_generator import generate_print_image, generate_print_pdf


@dataclass
class RenderJob:
    id: str
    status: str  # queued, running, completed, failed
    created_at: str
    updated_at: str
    file_id: str
    dpi: int
    color_theme: str
    engine: str
    profile: str
    outputs: list[str]
    error: str | None = None
    result: dict[str, str] | None = None


_jobs: dict[str, RenderJob] = {}
_jobs_lock = asyncio.Lock()
_MAX_JOBS = 500


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_job_id() -> str:
    return f"rj_{uuid.uuid4().hex[:14]}"


async def create_render_job(
    *,
    svg: str,
    file_id: str,
    board_size: str,
    dpi: int,
    color_theme: str,
    outputs: list[str],
    engine: str = "svg_v1",
    profile: str = "professional_print",
) -> str:
    """Queue a high-resolution render job and return its ID."""
    now = _utc_iso()
    job = RenderJob(
        id=_new_job_id(),
        status="queued",
        created_at=now,
        updated_at=now,
        file_id=file_id,
        dpi=dpi,
        color_theme=color_theme,
        engine=engine,
        profile=profile,
        outputs=outputs,
    )
    async with _jobs_lock:
        if len(_jobs) >= _MAX_JOBS:
            # Evict oldest completed/failed jobs first.
            stale_ids = [
                jid for jid, j in _jobs.items()
                if j.status in {"completed", "failed"}
            ]
            for jid in stale_ids[:50]:
                _jobs.pop(jid, None)
        _jobs[job.id] = job

    asyncio.create_task(
        _run_render_job(
            job_id=job.id,
            svg=svg,
            file_id=file_id,
            board_size=board_size,
            dpi=dpi,
            color_theme=color_theme,
            outputs=outputs,
        )
    )
    return job.id


async def get_render_job(job_id: str) -> dict[str, Any] | None:
    async with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return None
        return {
            "job_id": job.id,
            "status": job.status,
            "created_at": job.created_at,
            "updated_at": job.updated_at,
            "file_id": job.file_id,
            "dpi": job.dpi,
            "color_theme": job.color_theme,
            "engine": job.engine,
            "profile": job.profile,
            "outputs": job.outputs,
            "result": job.result or {},
            "error": job.error,
        }


async def enqueue_render_job(
    *,
    svg: str,
    file_id: str,
    board_size: str,
    dpi: int,
    color_theme: str,
    outputs: list[str],
    engine: str = "svg_v1",
    profile: str = "professional_print",
) -> str:
    """Public API alias for queuing a render job."""
    return await create_render_job(
        svg=svg,
        file_id=file_id,
        board_size=board_size,
        dpi=dpi,
        color_theme=color_theme,
        outputs=outputs,
        engine=engine,
        profile=profile,
    )


async def get_render_job_result(job_id: str) -> dict[str, str] | None:
    """Return output key map only when a job is completed."""
    job = await get_render_job(job_id)
    if not job or job.get("status") != "completed":
        return None
    return job.get("result") or {}


async def _set_job_state(
    job_id: str,
    *,
    status: str,
    error: str | None = None,
    result: dict[str, str] | None = None,
) -> None:
    async with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return
        job.status = status
        job.updated_at = _utc_iso()
        job.error = error
        if result is not None:
            job.result = result


async def _run_render_job(
    *,
    job_id: str,
    svg: str,
    file_id: str,
    board_size: str,
    dpi: int,
    color_theme: str,
    outputs: list[str],
) -> None:
    await _set_job_state(job_id, status="running")
    result: dict[str, str] = {}
    try:
        use_maptiler_engine = str((await get_render_job(job_id) or {}).get("engine", "")) == "maptiler_static_v1"
        maptiler_png: bytes | None = None
        if use_maptiler_engine:
            maptiler_png = await render_maptiler_print_png(
                svg=svg,
                board_size=board_size,
                dpi=dpi,
            )

        if "png" in outputs:
            if maptiler_png is not None:
                png = maptiler_png
            else:
                png = generate_print_image(
                    svg,
                    skip_remap=True,
                    board_size=board_size,
                    dpi=dpi,
                    color_theme=color_theme,
                )
            png_key = f"render_jobs/{file_id}/{job_id}_print_{dpi}dpi.png"
            await store_file(png_key, png, content_type="image/png")
            result["png_key"] = png_key

        if "pdf" in outputs:
            if maptiler_png is not None:
                pdf = render_png_bytes_to_pdf(maptiler_png)
            else:
                pdf = generate_print_pdf(
                    svg,
                    board_size=board_size,
                    dpi=dpi,
                    color_theme=color_theme,
                    skip_remap=True,
                )
            pdf_key = f"render_jobs/{file_id}/{job_id}_print_{dpi}dpi.pdf"
            await store_file(pdf_key, pdf, content_type="application/pdf")
            result["pdf_key"] = pdf_key

        await _set_job_state(job_id, status="completed", result=result)
    except Exception as e:
        log.error(f"Render job {job_id} failed: {type(e).__name__}: {e}")
        await _set_job_state(job_id, status="failed", error=f"{type(e).__name__}: {e}")
