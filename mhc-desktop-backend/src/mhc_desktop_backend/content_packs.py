"""Bundled-content materialization for the packaged mhc-desktop app.

When running from the NSIS installer, electron-builder's
``extraResources`` copies ``packages/mhc-desktop-app/content-packs/``
to ``<resourcesPath>/content-packs/`` (see
``docs/PACKAGING-MHC-DESKTOP.md`` §3.6). On first launch this module
walks that tree and installs each unit into the user data dir
(``~/.mhc-desktop/{skills,mcp,tools}/``) using the same store APIs the
``/api/v1/{skills,tools,mcp}/import-bulk`` routes use.

User customizations are preserved: units whose slug already exists in
the store are skipped (unless ``overwrite=True``), so editing a bundled
skill's body or disabling a bundled tool is not undone by the next
launch.

In dev mode (``app.isPackaged == False``) the helper is a no-op;
content packs are imported manually through the management pages.

The same ``bulk_install_*`` functions back the ``import-bulk`` HTTP
routes — keeping a single code path for both the manual API and the
boot-time materialization means a fix in one place covers both.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Protocol

logger = logging.getLogger("mhc_desktop_backend")


class SkillLike(Protocol):
    """Structural surface ``bulk_install_skills`` needs from a skill store."""

    async def install_from_folder(
        self,
        source: Path,
        *,
        origin: str = ...,
        overwrite: bool = ...,
    ) -> Any: ...


class ToolLike(Protocol):
    """Structural surface ``bulk_install_tools`` needs from a tool store.

    Mirrors :class:`mhc_desktop_backend.protocols.ToolStoreProtocol` —
    the public methods plus the ``_dir`` attribute the import path
    writes its persisted source copy to. Adapters that don't follow
    that internal layout should not be passed here.
    """

    _dir: Path

    async def get(self, slug: str) -> Any: ...
    async def create(self, data: dict[str, Any]) -> Any: ...
    async def update(self, slug: str, data: dict[str, Any]) -> Any: ...


class MCPLike(Protocol):
    """Structural surface ``bulk_install_mcps`` needs from an MCP store."""

    _dir: Path

    async def get(self, slug: str) -> Any: ...
    async def upsert(
        self,
        *,
        slug: str,
        name: str,
        description: str,
        command: str,
        args: list[str],
        env: dict[str, str] | None,
        origin: str,
    ) -> Any: ...


# ── Public API ───────────────────────────────────────────────────────


async def materialize_bundled(
    *,
    content_root: Path | None,
    skill_store: SkillLike,
    tool_store: ToolLike,
    mcp_store: MCPLike,
    origin: str = "bundled",
    overwrite: bool = False,
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Install every unit under ``content_root/{skills,tools,mcp}/``.

    Returns ``{"skills": {"installed":[…],"skipped":[…],"errors":[…]},
    …}`` so callers can surface a one-time toast in the renderer or
    feed it to a test assertion. Missing domains (e.g. no ``mcp/``
    subdir) are simply absent from the result.

    ``content_root=None`` or a path that doesn't exist is a no-op
    (returns an empty summary). The caller decides whether to invoke
    us at all based on ``app.isPackaged``.
    """
    summary: dict[str, dict[str, list[dict[str, Any]]]] = {
        "skills": {"installed": [], "skipped": [], "errors": []},
        "tools": {"installed": [], "skipped": [], "errors": []},
        "mcp": {"installed": [], "skipped": [], "errors": []},
    }
    if content_root is None or not content_root.is_dir():
        logger.info("content_packs.no_root path=%s", content_root)
        return summary

    skills_dir = content_root / "skills"
    if skills_dir.is_dir():
        await bulk_install_skills(
            skills_dir,
            skill_store,
            origin=origin,
            overwrite=overwrite,
            summary=summary["skills"],
        )

    tools_dir = content_root / "tools"
    if tools_dir.is_dir():
        await bulk_install_tools(
            tools_dir,
            tool_store,
            origin=origin,
            overwrite=overwrite,
            summary=summary["tools"],
        )

    mcp_dir = content_root / "mcp"
    if mcp_dir.is_dir():
        await bulk_install_mcps(
            mcp_dir,
            mcp_store,
            origin=origin,
            overwrite=overwrite,
            summary=summary["mcp"],
        )

    for domain, counts in (
        ("skills", summary["skills"]),
        ("tools", summary["tools"]),
        ("mcp", summary["mcp"]),
    ):
        logger.info(
            "content_packs.%s installed=%d skipped=%d errors=%d",
            domain,
            len(counts["installed"]),
            len(counts["skipped"]),
            len(counts["errors"]),
        )
    return summary


async def bulk_install_skills(
    root: Path,
    store: SkillLike,
    *,
    origin: str = "imported",
    overwrite: bool = False,
    summary: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Walk ``root`` for leaf dirs containing ``SKILL.md`` and install.

    A non-leaf dir is recursed into — content packs sometimes nest
    skills one extra level (e.g. ``category/<slug>/SKILL.md``).

    Returns ``summary`` (or a fresh dict if ``summary is None``) with
    ``installed`` / ``skipped`` / ``errors`` keys so callers can
    aggregate or assert.
    """
    summary = summary or {"installed": [], "skipped": [], "errors": []}
    if not root.is_dir():
        summary["errors"].append({"path": str(root), "error": "not a directory"})
        return summary
    # The root itself is a skill (rare but valid).
    if (root / "SKILL.md").is_file():
        await _try_install_skill(store, root, origin, overwrite, summary)
        return summary
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        if (child / "SKILL.md").is_file():
            await _try_install_skill(store, child, origin, overwrite, summary)
        else:
            await bulk_install_skills(
                child, store, origin=origin, overwrite=overwrite, summary=summary
            )
    return summary


async def bulk_install_tools(
    root: Path,
    store: ToolLike,
    *,
    origin: str = "imported",
    overwrite: bool = False,
    summary: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Walk ``root`` for leaf dirs containing ``tool.py`` and install.

    Optional ``manifest.json`` next to ``tool.py`` declares the tool's
    display name, description, parameters schema, version, license —
    matching the Anthropic portable format the ``/import-bulk`` route
    already consumes.

    The tool's Python source is copied into the store's per-slug
    directory so it survives backend restarts (process-local callable
    cache is wiped on every uvicorn reload — see ``api/tools.py``
    ``_resolve_callable`` for the lazy re-import).
    """
    # Lazy import: tools.imports pulls optional deps; only needed when
    # the pack actually carries tools.
    from mhc_desktop_backend.tools.imports import import_local_tool
    from mhc_desktop_backend.tools.models import slugify as tool_slugify

    summary = summary or {"installed": [], "skipped": [], "errors": []}
    if not root.is_dir():
        summary["errors"].append({"path": str(root), "error": "not a directory"})
        return summary
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        tp = child / "tool.py"
        if not tp.is_file():
            await bulk_install_tools(
                child, store, origin=origin, overwrite=overwrite, summary=summary
            )
            continue
        slug = tool_slugify(child.name)
        if not slug:
            summary["skipped"].append({"path": str(child), "reason": "empty slug"})
            continue
        existing = await store.get(slug)
        if existing is not None and not overwrite:
            # Existing install: leave user customisations alone,
            # but seed any kernel-owned fields the manifest now
            # carries that the stored entry doesn't (today:
            # ``display_name_i18n``). Cheap diff-update so adding
            # a new localised name doesn't require a wipe.
            manifest_path_existing = child / "manifest.json"
            if manifest_path_existing.is_file():
                try:
                    ex_meta = json.loads(manifest_path_existing.read_text("utf-8"))
                except json.JSONDecodeError:
                    ex_meta = {}
                i18n_seed = ex_meta.get("display_name_i18n") or {}
                if i18n_seed and not getattr(existing, "display_name_i18n", {}):
                    try:
                        await store.update(slug, {"display_name_i18n": dict(i18n_seed)})
                    except Exception as e:  # noqa: BLE001
                        summary["errors"].append({
                            "path": str(child),
                            "error": f"failed to seed i18n: {e}",
                        })
            summary["skipped"].append(
                {"path": str(child), "reason": f"tool '{slug}' already exists"}
            )
            continue
        manifest_path = child / "manifest.json"
        meta: dict[str, Any] = {}
        if manifest_path.is_file():
            try:
                meta = json.loads(manifest_path.read_text("utf-8"))
            except json.JSONDecodeError:
                meta = {}
        source = tp.read_text("utf-8")
        try:
            await import_local_tool(slug, source)
        except (ValueError, SyntaxError) as e:
            summary["errors"].append({"path": str(child), "error": str(e)})
            continue
        dest_dir = store._dir / slug
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / "tool.py"
            dest.write_text(source, encoding="utf-8")
            dest_source = str(dest)
        except OSError as e:
            summary["errors"].append(
                {"path": str(child), "error": f"failed to persist tool source: {e}"}
            )
            continue
        payload = {
            "slug": slug,
            "name": meta.get("name") or slug,
            "description": meta.get("description", ""),
            "kind": "local",
            "parameters": meta.get("parameters")
            or {"type": "object", "properties": {}},
            "origin": origin,
            "source_path": dest_source,
            "version": meta.get("version", ""),
            "license": meta.get("license", ""),
            "enabled": True,
            "display_name_i18n": meta.get("display_name_i18n", {}) or {},
        }
        try:
            if existing is not None and overwrite:
                tool = await store.update(slug, payload)
            else:
                tool = await store.create(payload)
        except Exception as e:
            summary["errors"].append({"path": str(child), "error": str(e)})
            continue
        summary["installed"].append({"slug": tool.slug, "path": str(child)})
    return summary


async def bulk_install_mcps(
    root: Path,
    store: MCPLike,
    *,
    origin: str = "imported",
    overwrite: bool = False,
    summary: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Walk ``root`` for leaf dirs containing ``config.json`` and install.

    Schema mirrors what the ``/api/v1/mcp/import-bulk`` route accepts
    (slug/name/description/command/args/env in ``config.json``).
    """
    summary = summary or {"installed": [], "skipped": [], "errors": []}
    if not root.is_dir():
        summary["errors"].append({"path": str(root), "error": "not a directory"})
        return summary
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        cfg = child / "config.json"
        if not cfg.is_file():
            await bulk_install_mcps(
                child, store, origin=origin, overwrite=overwrite, summary=summary
            )
            continue
        try:
            data = json.loads(cfg.read_text("utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            summary["errors"].append(
                {"path": str(child), "error": f"bad config.json: {e}"}
            )
            continue
        # We must hit the same slug the store would compute, otherwise
        # the "already exists" check below races the store's own slug.
        from mhc_desktop_backend.mcp.models import slugify as mcp_slugify

        desired_slug = mcp_slugify(str(data.get("slug") or child.name))
        if not desired_slug:
            summary["skipped"].append({"path": str(child), "reason": "empty slug"})
            continue
        existing = await store.get(desired_slug)
        if existing is not None and not overwrite:
            summary["skipped"].append(
                {"path": str(child), "reason": f"mcp '{desired_slug}' already exists"}
            )
            continue
        try:
            srv = await store.upsert(
                slug=desired_slug,
                name=str(data.get("name") or child.name),
                description=str(data.get("description") or ""),
                command=str(data.get("command") or ""),
                args=[str(a) for a in (data.get("args") or [])],
                env={str(k): str(v) for k, v in (data.get("env") or {}).items()},
                origin=origin,
            )
        except Exception as e:
            msg = str(e)
            if "already exists" in msg.lower():
                summary["skipped"].append({"path": str(child), "reason": msg})
            else:
                summary["errors"].append({"path": str(child), "error": msg})
            continue
        summary["installed"].append({"slug": srv.slug, "path": str(child)})
    return summary


# ── Internal helpers ─────────────────────────────────────────────────


async def _try_install_skill(
    store: SkillLike,
    folder: Path,
    origin: str,
    overwrite: bool,
    summary: dict[str, list[dict[str, Any]]],
) -> None:
    try:
        skill = await store.install_from_folder(
            folder, origin=origin, overwrite=overwrite
        )
    except Exception as e:
        msg = str(e)
        if "already exists" in msg.lower():
            summary["skipped"].append({"path": str(folder), "reason": msg})
        else:
            summary["errors"].append({"path": str(folder), "error": msg})
        return
    summary["installed"].append({"slug": skill.slug, "path": str(folder)})
