"""Anonymous BuildDraft endpoints.

A BuildDraft lets an anonymous buyer design a map and save it server-side
before they commit to a purchase.  No user account is required.

Typical flow
------------
1. ``POST /api/v1/drafts``           — create a new draft, get back a token.
2. ``PATCH /api/v1/drafts/{token}``  — update the design config as the user
                                       refines their map.
3. ``GET  /api/v1/drafts/{token}``   — retrieve the current draft state.
4. ``POST /api/v1/etsy/push``        — push the draft to Etsy as a listing.

Drafts expire after 7 days by default.  Expired drafts are not deleted
automatically but the fulfilment worker skips them.
"""

import json
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.logging_config import log
from app.models.db_models import BuildDraft

router = APIRouter(prefix="/api/v1/drafts", tags=["drafts"])

_DRAFT_TTL_DAYS = 7


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class DraftCreateRequest(BaseModel):
    design_config: dict | None = None
    session_key: str | None = None  # optional browser fingerprint


class DraftUpdateRequest(BaseModel):
    design_config: dict


class DraftResponse(BaseModel):
    draft_token: str
    design_config: dict | None = None
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("", response_model=DraftResponse, status_code=201)
async def create_draft(req: DraftCreateRequest, db: AsyncSession = Depends(get_db)):
    """Create a new anonymous build draft and return its token."""
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=_DRAFT_TTL_DAYS)

    draft = BuildDraft(
        draft_token=token,
        design_config=json.dumps(req.design_config) if req.design_config else None,
        session_key=req.session_key,
        expires_at=expires_at,
    )
    db.add(draft)
    await db.commit()
    await db.refresh(draft)

    log.info("BuildDraft %s created (expires %s)", token, expires_at.date())

    return _to_response(draft)


@router.get("/{token}", response_model=DraftResponse)
async def get_draft(token: str, db: AsyncSession = Depends(get_db)):
    """Retrieve an existing build draft by its token."""
    result = await db.execute(
        select(BuildDraft).where(BuildDraft.draft_token == token)
    )
    draft = result.scalar_one_or_none()

    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found.")

    _check_expiry(draft)
    return _to_response(draft)


@router.patch("/{token}", response_model=DraftResponse)
async def update_draft(token: str, req: DraftUpdateRequest, db: AsyncSession = Depends(get_db)):
    """Update the design config of an existing build draft."""
    result = await db.execute(
        select(BuildDraft).where(BuildDraft.draft_token == token)
    )
    draft = result.scalar_one_or_none()

    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found.")

    _check_expiry(draft)

    draft.design_config = json.dumps(req.design_config)
    await db.commit()
    await db.refresh(draft)

    log.debug("BuildDraft %s updated", token)
    return _to_response(draft)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _check_expiry(draft: BuildDraft) -> None:
    if draft.expires_at is None:
        return
    now = datetime.now(timezone.utc)
    # Normalise: SQLite returns naive datetimes; treat them as UTC.
    expires = draft.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < now:
        raise HTTPException(status_code=410, detail="This draft has expired.")


def _to_response(draft: BuildDraft) -> DraftResponse:
    config = None
    if draft.design_config:
        try:
            config = json.loads(draft.design_config)
        except (json.JSONDecodeError, TypeError):
            config = None

    return DraftResponse(
        draft_token=draft.draft_token,
        design_config=config,
        created_at=draft.created_at,
        updated_at=draft.updated_at,
        expires_at=draft.expires_at,
    )
