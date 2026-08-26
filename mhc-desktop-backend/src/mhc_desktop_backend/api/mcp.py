"""MCP HTTP API.

All endpoints are under ``/api/v1/mcp``.

* ``GET    /``                list configured MCP servers
* ``GET    /bundled``         legacy — always returns []
* ``GET    /{slug}``          detail (incl. discovered tools)
* ``GET    /{slug}/tools``    force re-discovery + return catalog
* ``POST   /``                upsert one server (no live connect)
* ``POST   /import-bulk``     install every MCP subfolder in a folder
                              or zip (each subfolder holds config.json)
* ``PUT    /{slug}/enabled``  toggle enabled flag
* ``DELETE /{slug}``          remove

MCP subprocess spawning lives on the manager; the API surface is
read/write config only. Tool execution goes through
``POST /api/v1/chat`` with ``mcp: [slug]`` in the request body, not
through a dedicated endpoint.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from fastapi.responses import Response

from mhc_desktop_backend.content_packs import bulk_install_mcps
from mhc_desktop_backend.mcp import MCPError, MCPManager
from mhc_desktop_backend.protocols import MCPStoreProtocol

logger = logging.getLogger("mhc_desktop_backend")

router = APIRouter(prefix="/api/v1/mcp", tags=["mcp"])


def get_store(request: Request) -> MCPStoreProtocol:
    store: MCPStoreProtocol | None = getattr(request.app.state, "mcp_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="MCP store not initialized")
    return store


def get_manager(request: Request) -> MCPManager:
    mgr: MCPManager | None = getattr(request.app.state, "mcp_manager", None)
    if mgr is None:
        raise HTTPException(status_code=503, detail="MCP manager not initialized")
    return mgr


@router.get("")
async def list_mcps(
    store: MCPStoreProtocol = Depends(get_store),
) -> list[dict[str, Any]]:
    return [s.public_dict() for s in await store.list()]


@router.get("/{slug}")
async def get_mcp(
    slug: str, store: MCPStoreProtocol = Depends(get_store)
) -> dict[str, Any]:
    srv = await store.get(slug)
    if srv is None:
        raise HTTPException(status_code=404, detail=f"MCP '{slug}' not found")
    return srv.public_dict()


@router.get("/{slug}/tools")
async def refresh_tools(
    slug: str,
    store: MCPStoreProtocol = Depends(get_store),
    manager: MCPManager = Depends(get_manager),
) -> dict[str, Any]:
    """Force a tools/list round-trip and return the catalog.

    Used by the management page when the user clicks \"Refresh\" \u2014
    a regular ``GET /{slug}`` only returns the cached catalog from
    disk (which may be stale until first connect).
    """
    srv = await store.get(slug)
    if srv is None:
        raise HTTPException(status_code=404, detail=f"MCP '{slug}' not found")
    try:
        tools = await manager.list_tools(srv)
    except MCPError as e:
        raise HTTPException(status_code=502, detail=str(e)) from None
    return {"slug": slug, "tools": tools}


@router.post("", status_code=status.HTTP_201_CREATED)
async def upsert_mcp(
    body: dict[str, Any] = Body(...),
    store: MCPStoreProtocol = Depends(get_store),
) -> dict[str, Any]:
    name = (body.get("name") or "").strip()
    description = (body.get("description") or "").strip()
    command = (body.get("command") or "").strip()
    args = body.get("args") or []
    env = body.get("env") or {}
    slug = (body.get("slug") or "").strip()
    origin = (body.get("origin") or "imported").strip() or "imported"
    # Optional localized display names; ignored on the wire if
    # not a dict of strings so a stray client can't crash us.
    raw_i18n = body.get("display_name_i18n")
    display_name_i18n: dict[str, str] | None = None
    if isinstance(raw_i18n, dict):
        display_name_i18n = {str(k): str(v) for k, v in raw_i18n.items() if isinstance(k, str) and isinstance(v, str)}
    if not command:
        raise HTTPException(status_code=400, detail="command is required")
    if not isinstance(args, list):
        raise HTTPException(status_code=400, detail="args must be a list")
    if not isinstance(env, dict):
        raise HTTPException(status_code=400, detail="env must be a dict")
    if not name:
        # Derive a display name from the command so the user doesn't
        # have to type it twice.
        name = (command.split() or ["MCP"])[0]
    try:
        srv = await store.upsert(
            slug=slug,
            name=name,
            description=description,
            command=command,
            args=[str(a) for a in args],
            env={str(k): str(v) for k, v in env.items()},
            origin=origin,
            display_name_i18n=display_name_i18n,
        )
    except MCPError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    return srv.public_dict()


@router.put("/{slug}/enabled")
async def toggle_mcp(
    slug: str,
    body: dict[str, Any],
    store: MCPStoreProtocol = Depends(get_store),
) -> dict[str, Any]:
    enabled = body.get("enabled")
    if not isinstance(enabled, bool):
        raise HTTPException(status_code=400, detail="enabled must be a boolean")
    try:
        srv = await store.set_enabled(slug, enabled)
    except MCPError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    return srv.public_dict()


@router.put("/{slug}")
async def edit_mcp(
    slug: str,
    body: dict[str, Any],
    store: MCPStoreProtocol = Depends(get_store),
) -> dict[str, Any]:
    """Edit the user-facing fields of an MCP server in place.

    Bundled MCPs are read-only by policy. Everything else can be
    renamed, had its description changed, or had its command /
    args / env rewritten. Slug stays put so the disk folder is
    stable; the operator is expected to delete + recreate if they
    want a slug rename.
    """
    existing = await store.get(slug)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"MCP '{slug}' not found")
    name = (body.get("name") or "").strip() or existing.name
    description = body.get("description")
    if description is None:
        description = existing.description
    command = (body.get("command") or "").strip() or existing.command
    args = body.get("args")
    if args is None:
        args = list(existing.args)
    elif not isinstance(args, list):
        raise HTTPException(status_code=400, detail="args must be a list")
    env = body.get("env")
    if env is None:
        env = dict(existing.env)
    elif not isinstance(env, dict):
        raise HTTPException(status_code=400, detail="env must be a dict")
    try:
        srv = await store.upsert(
            slug=slug,
            name=name,
            description=description,
            command=command,
            args=[str(a) for a in args],
            env={str(k): str(v) for k, v in env.items()},
            origin=existing.origin,
        )
    except MCPError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    return srv.public_dict()


@router.get("/{slug}/export")
async def export_mcp(
    slug: str, store: MCPStoreProtocol = Depends(get_store)
) -> Response:
    """Return the MCP config as a downloadable JSON document.

    Symmetrical to the skills export — lets the user back up an MCP
    spec to disk or share it with another instance. The exported
    payload is reproducible so re-importing it round-trips cleanly.
    """
    srv = await store.get(slug)
    if srv is None:
        raise HTTPException(status_code=404, detail=f"MCP '{slug}' not found")

    payload = {
        "format": "mhc-mcp/v1",
        "slug": srv.slug,
        "name": srv.name,
        "description": srv.description,
        "command": srv.command,
        "args": list(srv.args),
        "env": dict(srv.env),
    }
    body = json.dumps(payload, indent=2, ensure_ascii=False)
    return Response(
        content=body,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{slug}.mcp.json"',
        },
    )


@router.post("/import-bulk", status_code=status.HTTP_201_CREATED)
async def import_bulk(
    body: dict[str, Any] = Body(...),
    store: MCPStoreProtocol = Depends(get_store),
) -> dict[str, Any]:
    """Install every MCP subfolder inside a folder or a zip.

    Body is one of::

        {"source": "C:\\\\packs\\\\my-mcps"}               # folder
        {"data":   "<base64 zip>"}                        # zip

    Each MCP must live in its own subfolder containing a ``config.json``
    describing the spawn vector (command + args). The whole thing is
    upserted into the user's managed MCP dir.
    """
    summary: dict[str, list[dict[str, Any]]] = {
        "installed": [],
        "skipped": [],
        "errors": [],
    }
    overwrite = bool(body.get("overwrite", False))

    if "source" in body:
        raw = (body.get("source") or "").strip()
        if not raw:
            raise HTTPException(status_code=400, detail="source path is required")
        root = Path(raw)
        if not root.is_absolute():
            raise HTTPException(
                status_code=400, detail="source must be an absolute path"
            )
        if not root.exists():
            raise HTTPException(
                status_code=400, detail=f"source '{raw}' does not exist"
            )
        await bulk_install_mcps(
            root if root.is_dir() else root.parent,
            store,
            origin="imported",
            overwrite=overwrite,
            summary=summary,
        )
    elif "data" in body:
        b64 = body.get("data")
        if not isinstance(b64, str) or not b64:
            raise HTTPException(status_code=400, detail="zip data (base64) required")
        try:
            raw_bytes = base64.b64decode(b64, validate=True)
        except Exception as e:
            raise HTTPException(
                status_code=400, detail=f"invalid base64: {e}"
            ) from None
        if len(raw_bytes) > 50 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="zip too large (>50 MiB)")
        try:
            with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
                for n in zf.namelist():
                    zf.getinfo(n)
        except zipfile.BadZipFile as e:
            raise HTTPException(
                status_code=400, detail=f"not a valid zip: {e}"
            ) from None
        with tempfile.TemporaryDirectory() as td:
            tmp_root = Path(td)
            zip_path = tmp_root / "_bulk.zip"
            zip_path.write_bytes(raw_bytes)
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(tmp_root / "extracted")
            await bulk_install_mcps(
                tmp_root / "extracted",
                store,
                origin="imported",
                overwrite=overwrite,
                summary=summary,
            )
    else:
        raise HTTPException(status_code=400, detail="source or data is required")

    logger.info(
        "mcp.import-bulk installed=%d skipped=%d errors=%d",
        len(summary["installed"]),
        len(summary["skipped"]),
        len(summary["errors"]),
    )
    # The shared helper records {slug, path} per install — re-fetch the
    # full MCPServer so the HTTP response matches the legacy public_dict()
    # shape the renderer still consumes.
    for entry in summary["installed"]:
        slug = entry.get("slug")
        if not slug:
            continue
        full = await store.get(slug)
        if full is not None:
            entry.clear()
            entry.update(full.public_dict())
    return summary


@router.delete("/{slug}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mcp(slug: str, store: MCPStoreProtocol = Depends(get_store)) -> None:
    try:
        await store.delete(slug)
    except MCPError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
