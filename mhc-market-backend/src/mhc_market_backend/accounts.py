"""Simple account + token layer for the market web frontend.

The desktop client authenticates via the kernel's HMAC headers (see
``auth.py``). The standalone web app has no kernel in front of it, so
it logs in with username/password against the same demo accounts the
desktop ships with, and uses the returned Bearer token.

Admin: a subset of ``_ADMIN_USERS`` (driven by env
``MHC_MARKET_ADMIN_USERS``, comma-separated) get an ``admin`` flag on
their token. Ops endpoints require an admin-flagged token (or the
``X-MHC-Admin`` header) so ordinary users can't read business metrics.

ponytail: in-memory token dict with a fixed TTL. Swap for a real IdP
adapter when this graduates.
"""

from __future__ import annotations

import os
import secrets
import threading
import time

from fastapi import HTTPException, Request

from .auth import verify_headers

# Same demo accounts as the desktop app (deploy/impls/auth/mock.py).
_ACCOUNTS: dict[str, str] = {
    "alice": "wonderland",
    "bob": "builder",
    "demo": "demo",
}

# Admin-enabled usernames. Every demo account is admin in dev; prod
# sets MHC_MARKET_ADMIN_USERS to an explicit allow-list.
_ADMIN_USERS: frozenset[str] = frozenset(
    u.strip() for u in os.environ.get("MHC_MARKET_ADMIN_USERS", "alice,bob,demo").split(",") if u.strip()
)

# Bearer token TTL (seconds). Simple fixed expiry; no sliding renewal.
# ponytail: in-memory, pruned lazily on each check. Swap for a real IdP
# adapter when this graduates.
TOKEN_TTL = 24 * 60 * 60

_tokens: dict[str, tuple[str, float, bool]] = {}  # token -> (user, expires_at, is_admin)
_lock = threading.Lock()


def login(username: str, password: str) -> tuple[str, bool]:
    """Return ``(token, is_admin)``."""
    if _ACCOUNTS.get(username) != password:
        raise HTTPException(status_code=401, detail="invalid username or password")
    token = secrets.token_urlsafe(24)
    is_admin = username in _ADMIN_USERS
    with _lock:
        _tokens[token] = (username, time.time() + TOKEN_TTL, is_admin)
    return token, is_admin


def resolve_user(request: Request, secret: str) -> str:
    """Bearer token (web) first, then kernel HMAC headers (desktop)."""
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        token = header[7:].strip()
        with _lock:
            entry = _tokens.get(token)
        if entry is None:
            raise HTTPException(status_code=401, detail="invalid or expired token")
        user, expires_at, _admin = entry
        if time.time() > expires_at:
            with _lock:
                _tokens.pop(token, None)
            raise HTTPException(status_code=401, detail="invalid or expired token")
        return user
    return verify_headers(secret, request)


def resolve_ops_user(request: Request, secret: str) -> str:
    """Like ``resolve_user`` but requires an admin-flagged bearer token
    (or the kernel HMAC path, which is trusted to be the app itself)."""
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        token = header[7:].strip()
        with _lock:
            entry = _tokens.get(token)
        if entry is None:
            raise HTTPException(status_code=401, detail="invalid or expired token")
        user, expires_at, is_admin = entry
        if time.time() > expires_at:
            with _lock:
                _tokens.pop(token, None)
            raise HTTPException(status_code=401, detail="invalid or expired token")
        if not is_admin:
            raise HTTPException(status_code=403, detail="admin role required")
        return user
    # Kernel HMAC headers are the trusted app identity — allow.
    return verify_headers(secret, request)


__all__ = ["login", "resolve_ops_user", "resolve_user"]
