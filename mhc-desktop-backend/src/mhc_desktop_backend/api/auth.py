"""HTTP routes for the auth subsystem.

* ``POST /api/v1/auth/login``  — exchange (username, password) for a token.
* ``POST /api/v1/auth/logout`` — invalidate the caller's current token.
* ``GET  /api/v1/auth/me``     — return the current principal.

The login endpoint is **not** protected by the auth middleware (it's
in :data:`DEFAULT_EXEMPT_PATHS`); ``/auth/logout`` and ``/auth/me``
*are* protected — they need the bearer token they operate on.

Why we don't read username/password from JSON in the SPA's localStorage:
the SPA keeps only the token, never the password. Login form posts
to ``/auth/login`` and forgets the password on success.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status

from mhc_desktop_backend.protocols import AuthProviderProtocol, AuthUser

logger = logging.getLogger("mhc_desktop_backend")

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _resolve_principal(request: Request) -> AuthUser:
    user: AuthUser | None = getattr(request.state, "user", None)
    if user is None:
        # Should never happen on a protected route — middleware
        # short-circuits with 401. Treat as 401 here too in case the
        # route is hit without the middleware installed.
        raise HTTPException(status_code=401, detail="not authenticated")
    return user


@router.post("/login")
async def login(
    body: dict[str, Any] = Body(...),
    request: Request = ...,  # type: ignore[assignment]
) -> dict[str, Any]:
    """Exchange username + password for a token + user record.

    Returns 401 on bad credentials (no detail that distinguishes
    unknown-user from bad-password, to keep enumeration attacks
    hard).
    """
    provider: AuthProviderProtocol | None = getattr(
        request.app.state, "auth_provider", None
    )
    if provider is None:
        raise HTTPException(status_code=503, detail="auth provider not initialized")
    username = str(body.get("username") or "").strip()
    password = str(body.get("password") or "")
    if not username or not password:
        raise HTTPException(
            status_code=400, detail="username and password are required"
        )
    result = await provider.login(username, password)
    if result is None:
        raise HTTPException(status_code=401, detail="invalid credentials")
    token, user = result
    return {
        "token": token,
        "user": {
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "avatar_url": user.avatar_url,
        },
        # When the auth provider supplied an upstream-market
        # credential for this user, ship it on the login response so
        # the SPA can persist it (localStorage) and re-attach it to
        # every subsequent request via ``X-MHC-Upstream-Auth``.
        # None for the mock; real IdP adapters fill this in.
        "upstream_credential": user.upstream_credentials.get("auth")
        if user.upstream_credentials
        else None,
    }


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    user: AuthUser = Depends(_resolve_principal),
) -> None:
    """Invalidate the caller's current token.

    Idempotent — calling on an unknown token is a no-op. We rely on
    the auth middleware to have placed ``request.state.auth_token``
    on the request, then call the provider's ``logout`` to remove it.
    """
    provider: AuthProviderProtocol | None = getattr(
        request.app.state, "auth_provider", None
    )
    if provider is None:
        raise HTTPException(status_code=503, detail="auth provider not initialized")
    token = getattr(request.state, "auth_token", "")
    if token:
        await provider.logout(token)


@router.get("/me")
async def me(user: AuthUser = Depends(_resolve_principal)) -> dict[str, Any]:
    """Return the current principal. Used by the SPA to restore
    the login state on cold start (it reads /me with the token it
    has stored locally).

    Also re-emits the upstream credential so the SPA can rehydrate
    it after a renderer reload — the auth provider may rotate
    upstream tokens (typical for OIDC refresh) so we always ask.
    """
    return {
        "user": {
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "avatar_url": user.avatar_url,
        },
        "upstream_credential": user.upstream_credentials.get("auth")
        if user.upstream_credentials
        else None,
    }
