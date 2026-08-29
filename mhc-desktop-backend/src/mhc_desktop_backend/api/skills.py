"""Skills HTTP API.

All endpoints are under ``/api/v1/skills``.

* ``GET    /``                        list installed skills
* ``GET    /bundled``                 legacy — always returns []
* ``GET    /{slug}``                  skill detail (incl. body)
* ``GET    /{slug}/file?path=...``    read a non-SKILL.md file in the skill
* ``GET    /{slug}/download``         download a zip bundle
* ``POST   /import-folder``           install from a server-side path
* ``POST   /import-zip``              install from an uploaded zip body
* ``POST   /import-bulk``             install every skill folder inside
                                     a folder (recursive) or a zip
* ``PUT    /{slug}``                  edit description / body
* ``PUT    /{slug}/enabled``          toggle enabled flag
* ``DELETE /{slug}``                  remove

Folder import is a two-step flow on Windows because the renderer
can't push a folder across the IPC boundary directly:

1. The Electron main process receives the user's folder selection via
   the system dialog, copies it to a staging dir, and hands us the
   absolute path.
2. The renderer calls ``POST /import-folder`` with that path.

Zip import takes the raw bytes directly because that's a single
file and avoids the staging dance.
"""

from __future__ import annotations

import base64
import logging
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response

from mhc_desktop_backend.content_packs import bulk_install_skills
from mhc_desktop_backend.protocols import SkillStoreProtocol
from mhc_desktop_backend.skills import SkillError

logger = logging.getLogger("mhc_desktop_backend")

router = APIRouter(prefix="/api/v1/skills", tags=["skills"])


def get_store(request: Request) -> SkillStoreProtocol:
    store: SkillStoreProtocol | None = getattr(request.app.state, "skill_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="skill store not initialized")
    return store


@router.get("")
async def list_skills(
    store: SkillStoreProtocol = Depends(get_store),
) -> list[dict[str, Any]]:
    out = []
    for s in await store.list():
        d = s.public_dict()
        try:
            # Content fingerprint: fallback matcher, kept for compat.
            d["sha"] = await store.content_sha(s.slug)
        except SkillError:
            d["sha"] = ""
        out.append(d)
    return out


@router.get("/{slug}")
async def get_skill(
    slug: str, store: SkillStoreProtocol = Depends(get_store)
) -> dict[str, Any]:
    try:
        skill = await store.get(slug)
    except SkillError as e:
        # Malformed SKILL.md (bad YAML frontmatter, missing file, …)
        # is a client-fixable problem, not a server fault.
        raise HTTPException(status_code=400, detail=str(e)) from None
    if skill is None:
        raise HTTPException(status_code=404, detail=f"skill '{slug}' not found")
    return skill.to_dict()


@router.get("/{slug}/file")
async def get_skill_file(
    slug: str,
    path: str = Query(..., description="path relative to skill root"),
    store: SkillStoreProtocol = Depends(get_store),
) -> Response:
    try:
        ctype, data = await store.get_file(slug, path)
    except SkillError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    media = {
        "md": "text/markdown",
        "markdown": "text/markdown",
        "txt": "text/plain; charset=utf-8",
        "json": "application/json",
        "yaml": "text/yaml",
        "yml": "text/yaml",
        "py": "text/x-python",
        "js": "text/javascript",
        "ts": "text/typescript",
        "html": "text/html",
        "css": "text/css",
        "csv": "text/csv",
        "toml": "text/plain; charset=utf-8",
        "sh": "text/x-shellscript",
    }.get(ctype, "application/octet-stream")
    return Response(content=data, media_type=media)


@router.get("/{slug}/download")
async def download_skill(
    slug: str, store: SkillStoreProtocol = Depends(get_store)
) -> Response:
    try:
        blob = await store.export(slug)
    except SkillError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    return Response(
        content=blob,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{slug}.skill.zip"',
        },
    )


def _is_acceptable_source(p: Path) -> bool:
    """Accept absolute paths.

    Earlier versions restricted to the user's home directory as a
    coarse allow-list, but customers reasonably need to import
    skills from any shared / project folder. The renderer is the
    only thing that can hand us a path (it picked the file with a
    system dialog), so absolute-path requirement is the right gate.
    """
    return p.is_absolute()


@router.post("/import-folder", status_code=status.HTTP_201_CREATED)
async def import_folder(
    body: dict[str, Any] = Body(...),
    store: SkillStoreProtocol = Depends(get_store),
) -> dict[str, Any]:
    raw = (body.get("source") or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="source path is required")
    source = Path(raw)
    if not source.is_absolute():
        raise HTTPException(status_code=400, detail="source must be an absolute path")
    if not _is_acceptable_source(source):
        raise HTTPException(status_code=400, detail="source must be an absolute path")
    overwrite = bool(body.get("overwrite", False))
    try:
        skill = await store.install_from_folder(source, overwrite=overwrite)
    except SkillError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    return skill.public_dict()


@router.post("/import-zip", status_code=status.HTTP_201_CREATED)
async def import_zip(
    body: dict[str, Any] = Body(...),
    store: SkillStoreProtocol = Depends(get_store),
) -> dict[str, Any]:
    """Install a skill from base64-encoded zip data."""
    b64 = body.get("data")
    if not isinstance(b64, str) or not b64:
        raise HTTPException(status_code=400, detail="zip data (base64) required")
    try:
        raw = base64.b64decode(b64, validate=True)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"invalid base64: {e}") from None
    if len(raw) > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="zip too large (>20 MiB)")
    try:
        skill = await store.import_zip(raw)
    except SkillError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    return skill.public_dict()


@router.post("/import-bulk", status_code=status.HTTP_201_CREATED)
async def import_bulk(
    body: dict[str, Any] = Body(...),
    store: SkillStoreProtocol = Depends(get_store),
) -> dict[str, Any]:
    """Install every skill folder inside a folder (recursive) or a zip.

    Body is one of::

        {"source": "C:\\\\packs\\\\my-skills"}            # folder
        {"data":   "<base64 zip>"}                        # zip

    A folder path is scanned recursively: any leaf directory that
    contains ``SKILL.md`` becomes one skill. The folder is *copied*
    into the user's managed skills dir; we don't mutate the source.
    A zip is extracted into a temp dir and scanned the same way.

    The point of bulk is that one content pack can carry many skills,
    so each one has its own folder underneath a common parent.
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
        await bulk_install_skills(
            root, store, origin="imported", overwrite=overwrite, summary=summary
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
        with tempfile.TemporaryDirectory() as td:
            tmp_root = Path(td)
            zip_path = tmp_root / "_bulk.zip"
            zip_path.write_bytes(raw_bytes)
            # Validate by opening the bytes; BadZipFile surfaces here.
            try:
                with zipfile.ZipFile(zip_path) as zf:
                    zf.extractall(tmp_root / "extracted")
            except zipfile.BadZipFile as e:
                raise HTTPException(
                    status_code=400, detail=f"not a valid zip: {e}"
                ) from None
            await bulk_install_skills(
                tmp_root / "extracted",
                store,
                origin="imported",
                overwrite=overwrite,
                summary=summary,
            )
    else:
        raise HTTPException(status_code=400, detail="source or data is required")

    # The shared helper records {slug, path} per install — re-fetch the
    # full Skill so the HTTP response matches the legacy public_dict()
    # shape the renderer still consumes.
    for entry in summary["installed"]:
        slug = entry.get("slug")
        if not slug:
            continue
        full = await store.get(slug)
        if full is not None:
            entry.clear()
            entry.update(full.public_dict())

    logger.info(
        "skills.import-bulk installed=%d skipped=%d errors=%d",
        len(summary["installed"]),
        len(summary["skipped"]),
        len(summary["errors"]),
    )
    return summary


@router.put("/{slug}")
async def update_skill(
    slug: str,
    body: dict[str, Any],
    store: SkillStoreProtocol = Depends(get_store),
) -> dict[str, Any]:
    description = body.get("description")
    body_md = body.get("body")
    if description is not None and not isinstance(description, str):
        raise HTTPException(status_code=400, detail="description must be a string")
    if body_md is not None and not isinstance(body_md, str):
        raise HTTPException(status_code=400, detail="body must be a string")
    try:
        skill = await store.update_meta(slug, description=description, body=body_md)
    except SkillError as e:
        msg = str(e)
        code = 404 if "not found" in msg else 400
        raise HTTPException(status_code=code, detail=msg) from None
    return skill.public_dict()


@router.put("/{slug}/enabled")
async def toggle_skill(
    slug: str,
    body: dict[str, Any],
    store: SkillStoreProtocol = Depends(get_store),
) -> dict[str, Any]:
    enabled = body.get("enabled")
    if not isinstance(enabled, bool):
        raise HTTPException(status_code=400, detail="enabled must be a boolean")
    try:
        skill = await store.set_enabled(slug, enabled)
    except SkillError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    return skill.public_dict()


@router.delete("/{slug}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_skill(
    slug: str, store: SkillStoreProtocol = Depends(get_store)
) -> None:
    try:
        await store.delete(slug)
    except SkillError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
