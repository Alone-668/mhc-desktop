"""HTTP middleware that enforces an :class:`AuthProviderProtocol`.

Install via :func:`install_auth`. Behaviour:

* Token comes from ``Authorization: Bearer <token>``.
* ``auth.resolve(token)`` is awaited on every request; result is
  cached on ``request.state.user`` for the duration of the request.
* Paths listed in ``exempt_paths`` skip the check entirely (auth
  endpoints themselves, the health probe, the static SPA mount).
* Missing / invalid token on a non-exempt request -> 401.

The default exempt set covers everything the SPA needs to render a
login screen without holding a token.
"""

from __future__ import annotations

import logging
from typing import Callable, Iterable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from mhc_desktop_backend.protocols import AuthProviderProtocol

logger = logging.getLogger("mhc_desktop_backend")

# ponytail: keep the default exempt set small and explicit. Adding a
# route here means "anyone can call this without a token"; the list
# is short on purpose so we notice when it grows.
DEFAULT_EXEMPT_PATHS: tuple[str, ...] = (
    # Login is always public. Logout + me need a token to operate;
    # they're NOT exempt — middleware populates ``request.state.user``
    # so the route handlers can read it.
    "/api/v1/auth/login",
    "/api/v1/health",
    "/api/v1/meta",
    "/api/v1/onboarding",
    "/ready",
    "/docs",
    "/openapi.json",
    "/favicon.svg",
    # SPA mount + static asset paths (vite in dev too).
    "/assets",
    "/fonts",
)


def install_auth(
    app: FastAPI,
    provider: AuthProviderProtocol,
    *,
    exempt_paths: Iterable[str] = DEFAULT_EXEMPT_PATHS,
    upstream_header_prefix: str = "x-mhc-upstream-",
    scope_required_for: Callable[[str], frozenset[str]] | None = None,
) -> None:
    """Attach token-checking middleware to ``app``.

    The middleware runs *after* the SPA-fallback middleware defined
    in :mod:`mhc_desktop_backend.app` so static asset GETs (which
    fall through to ``index.html``) don't need to authenticate.

    ``upstream_header_prefix`` headers on the inbound request are
    collected into ``request.state.upstream_headers`` so deploy
    adapters (e.g. a marketplace provider) can forward the user's
    upstream-market identity without us having to hardcode which
    specific header to look at. Default prefix ``x-mhc-upstream-``
    is namespaced so callers can't accidentally smuggle headers
    that look like internal control headers.

    ``scope_required_for`` is the RBAC seam. Pass a function that
    returns the set of scopes required to access a given request
    path (empty set means no scope check). The kernel calls it on
    every non-exempt request and rejects with 403 if the resolved
    user's :attr:`AuthUser.scopes` don't cover the required set.
    ``None`` (the default) disables scope enforcement — every
    authenticated user can hit every non-exempt route. Deploys that
    want a permission model pass a real callable here.
    """
    exempt = tuple(exempt_paths)
    prefix = upstream_header_prefix.lower()

    @app.middleware("http")
    async def _auth_middleware(request: Request, call_next):
        path = request.url.path
        if any(path == p or path.startswith(p + "/") for p in exempt):
            return await call_next(request)
        header = request.headers.get("authorization", "")
        if not header.lower().startswith("bearer "):
            return _unauth("missing bearer token")
        token = header[7:].strip()
        if not token:
            return _unauth("empty bearer token")
        user = await provider.resolve(token)
        if user is None:
            return _unauth("invalid or expired token")
        # Attach to request state so routes can read the principal.
        request.state.user = user
        request.state.auth_token = token
        # Capture namespace-prefixed headers verbatim. Strip the
        # ``x-mhc-upstream-`` prefix from the keys so the deploy
        # adapter sees a clean dict (``auth`` rather than
        # ``x-mhc-upstream-auth``).
        upstream: dict[str, str] = {}
        for k, v in request.headers.items():
            kl = k.lower()
            if kl.startswith(prefix):
                upstream[kl[len(prefix) :]] = v
        request.state.upstream_headers = upstream
        # RBAC gate — only fires if the deploy passed a callable.
        # Path-based rules live entirely in deploy so the kernel
        # never decides the vocabulary; the kernel only checks
        # subset on the principal's scope set.
        if scope_required_for is not None:
            required = scope_required_for(path)
            if required and not required.issubset(user.scopes):
                return JSONResponse(
                    status_code=403,
                    content={
                        "detail": (
                            f"missing scope(s): {sorted(required - user.scopes)}"
                        ),
                    },
                )
        return await call_next(request)


def _unauth(detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={"detail": detail},
        headers={"WWW-Authenticate": "Bearer"},
    )


__all__ = ["DEFAULT_EXEMPT_PATHS", "install_auth"]
