"""Authentication service — JWT tokens + password hashing.

Authentication channels
-----------------------
A request is authenticated if EITHER of these carries a valid
JWT with a known `sub`:

  1. `mapforge_session` cookie (`HttpOnly; Secure; SameSite=Strict`).
     Preferred. Set on login/register by `routers.auth`. XSS-safe
     because JavaScript can't read it.
  2. `Authorization: Bearer <token>` header. Kept as a compatibility
     channel for any external consumer (scripts, curl, mobile
     clients) that authenticates before we cut over to cookies
     only.

`get_current_user` / `get_optional_user` check the cookie first and
fall back to the bearer header. Rolling out cookies is therefore
non-breaking: old clients continue to work, and the frontend flips
to cookies without coordination.
"""

from datetime import datetime, timedelta, timezone

import base64
import hashlib

import bcrypt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.db_models import User

# Name of the auth cookie. Exported so routers/auth.py can keep
# the login / logout / middleware references in sync.
AUTH_COOKIE_NAME = "mapforge_session"

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


def _extract_token(request: Request, bearer_token: str | None) -> str | None:
    """Pull a JWT from the session cookie OR the bearer header.

    Cookie wins when both are present — it's the production path and
    keeps semantics unambiguous during the bearer-to-cookie migration.
    """
    cookie_token = request.cookies.get(AUTH_COOKIE_NAME)
    if cookie_token:
        return cookie_token
    return bearer_token


def _prep_password(password: str) -> bytes:
    """Pre-hash with SHA-256 to handle bcrypt's 72-byte limit. Returns bytes."""
    digest = hashlib.sha256(password.encode("utf-8")).digest()
    return base64.b64encode(digest)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prep_password(password), bcrypt.gensalt(rounds=12)).decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_prep_password(plain), hashed.encode("ascii"))
    except Exception:
        return False


def create_access_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": user_id, "exp": expire}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> str | None:
    """Returns user_id or None."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None


async def get_current_user(
    request: Request,
    bearer: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Dependency — requires valid auth token (cookie or bearer)."""
    token = _extract_token(request, bearer)
    if token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    user_id = decode_token(token)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    return user


async def get_optional_user(
    request: Request,
    bearer: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """Dependency — returns user if authenticated, None otherwise."""
    token = _extract_token(request, bearer)
    if token is None:
        return None

    user_id = decode_token(token)
    if user_id is None:
        return None

    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()
