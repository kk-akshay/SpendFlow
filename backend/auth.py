"""Email + password accounts with server-side sessions (httpOnly cookie)."""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, Response

from .config import COOKIE_NAME, COOKIE_SECURE, LEGACY_COOKIE_NAME, SESSION_DAYS
from .db import get_db

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def hash_password(password: str, salt: bytes | None = None) -> tuple[bytes, bytes]:
    salt = salt or os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return digest, salt


def verify_password(password: str, digest: bytes, salt: bytes) -> bool:
    return hmac.compare_digest(hash_password(password, salt)[0], digest)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def start_session(db, response: Response, user_id: int) -> None:
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
    db.execute("DELETE FROM sessions WHERE expires_at < ?", (datetime.now(timezone.utc).isoformat(),))
    db.execute(
        "INSERT INTO sessions(token_hash,user_id,expires_at) VALUES(?,?,?)",
        (_token_hash(token), user_id, expires.isoformat()),
    )
    db.commit()
    response.set_cookie(
        COOKIE_NAME, token, max_age=SESSION_DAYS * 86400, httponly=True,
        samesite="lax", secure=COOKIE_SECURE, path="/",
    )


def end_session(db, request: Request, response: Response) -> None:
    for name in (COOKIE_NAME, LEGACY_COOKIE_NAME):
        token = request.cookies.get(name)
        if token:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (_token_hash(token),))
        response.delete_cookie(name, path="/")
    db.commit()


def require_csrf(request: Request) -> None:
    """State-changing calls must carry a custom header, which cross-site forms cannot send."""
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("x-requested-with") not in ("spendflow", "tally"):
        raise HTTPException(403, "Missing request header")


def current_user(request: Request, db=Depends(get_db)) -> dict:
    token = request.cookies.get(COOKIE_NAME) or request.cookies.get(LEGACY_COOKIE_NAME)
    if not token:
        raise HTTPException(401, "Please sign in")
    row = db.execute(
        "SELECT u.id, u.email, s.expires_at FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=?",
        (_token_hash(token),),
    ).fetchone()
    if not row or row["expires_at"] < datetime.now(timezone.utc).isoformat():
        raise HTTPException(401, "Your session has expired. Please sign in again.")
    return {"id": row["id"], "email": row["email"]}


# Tiny in-memory throttle against password guessing.
_attempts: dict[str, deque] = defaultdict(deque)


def throttle(key: str, limit: int = 8, window: int = 600) -> None:
    now = time.time()
    q = _attempts[key]
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= limit:
        raise HTTPException(429, "Too many attempts. Please wait a few minutes and try again.")
    q.append(now)


def clear_throttle(key: str) -> None:
    _attempts.pop(key, None)
