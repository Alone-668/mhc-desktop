"""HMAC identity headers shared between the kernel proxy and this service.

The kernel (which owns the real auth) forwards ``X-MHC-User`` plus a
signature over ``f"{user}:{ts}"`` using a shared secret. The market
service verifies the signature and the timestamp window, then trusts
the user name. No tokens, no password storage.
"""

from __future__ import annotations

import hashlib
import hmac
import time

from fastapi import HTTPException, Request

TS_WINDOW_SECONDS = 300


def sign(secret: str, user: str, ts: int) -> str:
    msg = f"{user}:{ts}".encode()
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


def verify_headers(secret: str, request: Request) -> str:
    """Return the verified user name or raise 401."""
    user = request.headers.get("x-mhc-user", "").strip()
    ts_raw = request.headers.get("x-mhc-ts", "").strip()
    sig = request.headers.get("x-mhc-sig", "").strip()
    if not user or not ts_raw or not sig:
        raise HTTPException(status_code=401, detail="missing identity headers")
    try:
        ts = int(ts_raw)
    except ValueError:
        raise HTTPException(status_code=401, detail="bad timestamp") from None
    if abs(time.time() - ts) > TS_WINDOW_SECONDS:
        raise HTTPException(status_code=401, detail="stale timestamp")
    if not hmac.compare_digest(sign(secret, user, ts), sig):
        raise HTTPException(status_code=401, detail="bad signature")
    return user


__all__ = ["TS_WINDOW_SECONDS", "sign", "verify_headers"]
