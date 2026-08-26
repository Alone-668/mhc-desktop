"""Runtime metadata endpoint.

``GET /api/v1/meta`` returns the deploy-provided manifest: brand
information, data directory, locale defaults, version — anything
the renderer or a desktop deployment probe might want without
having to crawl the rest of the API.

The endpoint is the contract surface between backend and the
forked frontend. Enterprises that customise the SPA still talk to
``/api/v1/meta`` rather than hard-coding strings; the deploy
package populates the manifest from the same brand / config
module the renderer reads at build time, so the two stay in
sync without shared source.

The endpoint is **always public** — no auth required. A renderer
that hasn't logged in yet still wants to know the app name and
default locale before showing the login screen.

The endpoint also serves the deploy-provided bundled-content
catalog (skill / MCP / tool slugs the deploy staged at
``content_packs_root``) so the renderer can render an "installed
out of the box" badge without making three separate requests to
the (now removed) ``/bundled`` legacy routes.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/v1/meta", tags=["meta"])


@router.get("")
async def get_meta(request: Request) -> dict:
    """Return the deploy-provided runtime manifest.

    Always returns 200 with at least ``{"meta": {}}`` — empty
    inner dict is a valid "no manifest wired" signal. The SPA
    treats missing keys as "use the bundled defaults" rather than
    as an error.
    """
    inner: dict = getattr(request.app.state, "meta", {}) or {}
    return {"meta": dict(inner)}


__all__ = ["router"]
