"""Tools CRUD router.

Mirrors the shape of :mod:`api.skills` and :mod:`api.mcp` so the
frontend can treat all three resources with the same mental model.
The slight difference: tools support import/export because a user
can hand-write a Python file with a ``tool_run`` entrypoint and
drop it in. Skills are also importable, MCP is only configurable
through the form.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from mhc_desktop_backend.content_packs import bulk_install_tools
from mhc_desktop_backend.protocols import ToolStoreProtocol
from mhc_desktop_backend.tools import ToolStoreError
from mhc_desktop_backend.tools.imports import import_local_tool

logger = logging.getLogger("mhc_desktop_backend")

router = APIRouter(prefix="/api/v1/tools", tags=["tools"])


def get_store(request: Request) -> ToolStoreProtocol:
    store: ToolStoreProtocol | None = getattr(request.app.state, "tool_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="tool store not initialized")
    return store


@router.get("")
async def list_tools(
    store: ToolStoreProtocol = Depends(get_store),
) -> list[dict[str, Any]]:
    return [t.public_dict() for t in await store.list()]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_tool(
    body: dict[str, Any],
    store: ToolStoreProtocol = Depends(get_store),
) -> dict[str, Any]:
    try:
        tool = await store.create(body)
    except ToolStoreError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    return tool.public_dict()


@router.get("/{slug}")
async def get_tool(
    slug: str, store: ToolStoreProtocol = Depends(get_store)
) -> dict[str, Any]:
    tool = await store.get(slug)
    if tool is None:
        raise HTTPException(status_code=404, detail=f"tool '{slug}' not found")
    return tool.public_dict()


@router.put("/{slug}")
async def update_tool(
    slug: str,
    body: dict[str, Any],
    store: ToolStoreProtocol = Depends(get_store),
) -> dict[str, Any]:
    try:
        tool = await store.update(slug, body)
    except ToolStoreError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    return tool.public_dict()


@router.put("/{slug}/enabled", status_code=status.HTTP_200_OK)
async def set_tool_enabled(
    slug: str,
    body: dict[str, Any],
    store: ToolStoreProtocol = Depends(get_store),
) -> dict[str, Any]:
    enabled = bool(body.get("enabled"))
    try:
        tool = await store.set_enabled(slug, enabled)
    except ToolStoreError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    return tool.public_dict()


@router.delete("/{slug}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tool(slug: str, store: ToolStoreProtocol = Depends(get_store)) -> None:
    try:
        await store.delete(slug)
    except ToolStoreError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    # Remove the persisted source copy so a re-import starts clean.
    import shutil

    dest_dir = store._dir / slug
    shutil.rmtree(dest_dir, ignore_errors=True)


@router.post("/import-source", status_code=status.HTTP_201_CREATED)
async def import_tool_from_source(
    body: dict[str, Any],
    store: ToolStoreProtocol = Depends(get_store),
) -> dict[str, Any]:
    """Import a local Python tool from inline source.

    Body::

        {
          "slug":   "my_tool",        # optional — derived from name
          "name":   "My Tool",
          "description": "...",
          "parameters": {...},         # optional JSON schema
          "source": "async def tool_run(...):\n    yield ...",
          "overwrite": false          # optional
        }

    The source must define ``async def tool_run(**kwargs)`` (or one
    of the aliases ``run`` / ``main`` / ``tool_callable``). The
    compiled module is held in a process-local cache so subsequent
    chat calls don't re-parse the source.
    """
    source = body.get("source")
    if not isinstance(source, str) or not source.strip():
        raise HTTPException(status_code=400, detail="source is required")
    slug_hint = (body.get("slug") or "").strip()
    overwrite = bool(body.get("overwrite", False))

    # Slug must be derivable now so we can register before importing.
    from mhc_desktop_backend.tools.models import slugify

    slug = slug_hint or slugify(body.get("name", ""))
    if not slug:
        raise HTTPException(status_code=400, detail="slug or name is required")

    existing = await store.get(slug)
    if existing is not None and not overwrite:
        raise HTTPException(
            status_code=409,
            detail=f"tool '{slug}' already exists (set overwrite=true to replace)",
        )

    try:
        await import_local_tool(slug, source)
    except (ValueError, SyntaxError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from None

    # Persist the source so the tool survives backend restarts (the
    # process-local callable cache is wiped on every uvicorn reload).
    dest_dir = store._dir / slug
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / "tool.py"
        dest.write_text(source, encoding="utf-8")
        dest_source = str(dest)
    except OSError as e:
        raise HTTPException(
            status_code=400, detail=f"failed to persist tool source: {e}"
        ) from None

    body_for_create = {
        "slug": slug,
        "name": body.get("name") or slug,
        "description": body.get("description", ""),
        "kind": "local",
        "parameters": body.get("parameters") or {"type": "object", "properties": {}},
        "origin": body.get("origin", "imported"),
        "source_path": dest_source,
    }
    if existing is not None and overwrite:
        try:
            tool = await store.update(slug, body_for_create)
        except ToolStoreError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None
    else:
        try:
            tool = await store.create(body_for_create)
        except ToolStoreError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None
    return tool.public_dict()


@router.post("/import-bulk", status_code=status.HTTP_201_CREATED)
async def import_bulk_tools(
    body: dict[str, Any],
    store: ToolStoreProtocol = Depends(get_store),
) -> dict[str, Any]:
    """Bulk-import every ``tool.py`` found in a folder (recursive) or a zip.

    Body is one of::

        {"source": "C:\\\\packs\\\\my-tools"}             # folder
        {"data":   "<base64 zip>"}                        # zip

    Each tool is a leaf directory containing a ``tool.py`` (the
    module the runtime ``exec``s). The slug is the directory name;
    the name / description / parameters are read from an optional
    ``manifest.json`` alongside ``tool.py`` if present:

        {
          "name": "Pretty Name",
          "description": "...",
          "parameters": { "type": "object", ... }
        }
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
        await bulk_install_tools(
            root if root.is_dir() else root.parent,
            store,
            origin="imported",
            overwrite=overwrite,
            summary=summary,
        )
    elif "data" in body:
        import base64
        import io
        import tempfile
        import zipfile

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
            await bulk_install_tools(
                tmp_root / "extracted",
                store,
                origin="imported",
                overwrite=overwrite,
                summary=summary,
            )
    else:
        raise HTTPException(status_code=400, detail="source or data is required")

    logger.info(
        "tools.import-bulk installed=%d skipped=%d errors=%d",
        len(summary["installed"]),
        len(summary["skipped"]),
        len(summary["errors"]),
    )
    # The shared helper records {slug, path} per install — re-fetch the
    # full Tool so the HTTP response matches the legacy public_dict()
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


@router.get("/{slug}/export")
async def export_tool(
    slug: str, store: ToolStoreProtocol = Depends(get_store)
) -> dict[str, Any]:
    """Return a portable manifest for one tool.

    For local tools, the manifest includes the Python source if
    available. For script / remote tools, just the configuration.
    """
    tool = await store.get(slug)
    if tool is None:
        raise HTTPException(status_code=404, detail=f"tool '{slug}' not found")

    out: dict[str, Any] = {
        "schema": "mhc-tool.v1",
        "slug": tool.slug,
        "name": tool.name,
        "description": tool.description,
        "kind": tool.kind,
        "parameters": tool.parameters,
    }
    if tool.kind == "remote":
        out["endpoint_url"] = tool.endpoint_url
        out["endpoint_auth_header"] = tool.endpoint_auth_header
    elif tool.kind == "script":
        out["script_path"] = tool.script_path
    return out
