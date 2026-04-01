"""High-resolution render job endpoints for professional print outputs."""

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.db_models import GeneratedFile, User
from app.models.schemas import (
    RenderJobCreateRequest,
    RenderJobCreateResponse,
    RenderJobOutputFormat,
    RenderJobOutput,
    RenderEngineProfile,
    RenderJobStatusResponse,
)
from app.services.auth import get_current_user
from app.services.file_storage import retrieve_file
from app.services.render_jobs import create_render_job, get_render_job

router = APIRouter(prefix="/api/v1/render", tags=["render"])


@router.post("/jobs", response_model=RenderJobCreateResponse)
async def create_job(
    req: RenderJobCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Queue a professional high-resolution render job (PNG/PDF)."""
    result = await db.execute(select(GeneratedFile).where(GeneratedFile.id == req.file_id))
    file_record = result.scalar_one_or_none()
    if not file_record:
        raise HTTPException(status_code=404, detail="Generated file not found.")
    if user.tier != "admin" and file_record.owner_id != user.id:
        raise HTTPException(status_code=403, detail="You do not own this file.")

    svg_bytes = await retrieve_file(file_record.svg_storage_key)
    if not svg_bytes:
        raise HTTPException(status_code=404, detail="Source SVG not found.")

    job_id = await create_render_job(
        svg=svg_bytes.decode("utf-8"),
        file_id=file_record.id,
        board_size=file_record.board_size,
        dpi=req.dpi,
        color_theme="classic",  # print SVG already themed
        outputs=[fmt.value for fmt in req.formats],
        profile=req.engine_profile.value,
    )
    return RenderJobCreateResponse(
        job_id=job_id,
        status="queued",
        engine_profile=req.engine_profile,
        formats=req.formats,
    )


@router.get("/jobs/{job_id}", response_model=RenderJobStatusResponse)
async def get_job_status(
    job_id: str,
    user: User = Depends(get_current_user),
):
    """Get render job status and downloadable output URLs when complete."""
    _ = user  # reserved for future owner checks when persisting jobs in DB
    job = await get_render_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Render job not found.")

    outputs: list[RenderJobOutput] = []
    result = job.get("result") or {}
    for fmt in job.get("outputs", []):
        key = result.get(f"{fmt}_key")
        fmt_enum = RenderJobOutputFormat(fmt)
        outputs.append(
            RenderJobOutput(
                format=fmt_enum,
                status="completed" if key else ("failed" if job["status"] == "failed" else job["status"]),
                content_type="application/pdf" if fmt == "pdf" else "image/png",
                download_url=f"/api/v1/render/download/{job_id}/{fmt}" if key else None,
                error=job.get("error") if job["status"] == "failed" else None,
            )
        )

    return RenderJobStatusResponse(
        job_id=job["job_id"],
        status=job["status"],
        file_id=job.get("file_id") or "",
        engine_profile=RenderEngineProfile(job.get("profile", "professional_print")),
        dpi=job.get("dpi", 600),
        formats=[RenderJobOutputFormat(fmt) for fmt in job.get("outputs", [])],
        outputs=outputs,
        error=job.get("error"),
    )


@router.get("/download/{job_id}/{fmt}")
async def download_job_output(
    job_id: str,
    fmt: str,
    user: User = Depends(get_current_user),
):
    """Download a completed render job output (png/pdf)."""
    _ = user  # ownership checks can be added once jobs are persisted in DB
    job = await get_render_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Render job not found.")
    if job.get("status") != "completed":
        raise HTTPException(status_code=409, detail="Render job is not completed yet.")

    fmt_l = fmt.lower()
    if fmt_l not in {"png", "pdf"}:
        raise HTTPException(status_code=400, detail="Unsupported render format.")

    key = (job.get("result") or {}).get(f"{fmt_l}_key")
    if not key:
        raise HTTPException(status_code=404, detail=f"{fmt_l.upper()} output is not available.")

    content = await retrieve_file(key)
    if content is None:
        raise HTTPException(status_code=404, detail="Rendered output not found in storage.")

    media_type = "application/pdf" if fmt_l == "pdf" else "image/png"
    filename = f"{job_id}.{fmt_l}"
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
