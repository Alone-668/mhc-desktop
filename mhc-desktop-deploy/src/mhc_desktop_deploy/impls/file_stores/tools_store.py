"""File-backed store for user-imported / user-created tools.

Each user tool lives at ``~/.mhc-desktop/tools/<slug>/`` as a
folder with a ``tool.py`` file (for ``kind: script``) plus a
``tools-state.json`` index for the enabled flags + meta outside the
folder itself (mirroring ``SkillStore`` and ``MCPStore``).

Locking is the same pattern the rest of the app uses — one
``asyncio.Lock`` per write so a fast save storm doesn't corrupt the
index file.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from pathlib import Path
from typing import Any

from mhc_desktop_backend.tools.errors import ToolStoreError
from mhc_desktop_backend.tools.models import Tool, now_iso, slugify

logger = logging.getLogger("mhc_desktop_backend")


class ToolStore:
    """Disk-backed CRUD for tool configs."""

    def __init__(self, tools_dir: Path | None = None) -> None:
        from mhc_desktop_deploy.impls.file_stores.paths import DATA_DIR

        self._dir = tools_dir or DATA_DIR / "tools"
        self._state_path = self._dir / "tools-state.json"
        self._entries: dict[str, dict[str, Any]] = {}
        self._loaded = False
        self._mtime: int | None = None
        self._write_lock = asyncio.Lock()

    def _state_mtime(self) -> int | None:
        try:
            return self._state_path.stat().st_mtime_ns
        except OSError:
            return None

    async def _ensure_loaded(self) -> None:
        mtime = self._state_mtime()
        if self._loaded and mtime == self._mtime:
            return
        self._entries = {}
        if self._state_path.exists():
            try:
                raw = json.loads(self._state_path.read_text("utf-8"))
            except json.JSONDecodeError:
                logger.exception("corrupt %s — ignoring", self._state_path)
                raw = {}
            dirty = False
            for entry in raw or []:
                slug = entry.get("slug")
                if not slug:
                    continue
                # Backfill id + model_name on older records that predate
                # the fields. Idempotent; safe on every load.
                if not entry.get("id"):
                    entry["id"] = str(uuid.uuid4())
                    dirty = True
                if "model_name" not in entry:
                    entry["model_name"] = ""
                self._entries[slug] = entry
            if dirty:
                self._persist()
        self._mtime = mtime
        self._loaded = True

    def _persist(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        index = list(self._entries.values())
        self._state_path.write_text(
            json.dumps(index, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        self._mtime = self._state_mtime()

    def _hydrate(self, entry: dict[str, Any]) -> Tool:
        """Convert one index entry into a :class:`Tool` dataclass."""
        return Tool(
            id=entry.get("id", ""),
            slug=entry.get("slug", ""),
            name=entry.get("name", ""),
            description=entry.get("description", ""),
            kind=entry.get("kind", "local"),
            parameters=entry.get("parameters") or {},
            endpoint_url=entry.get("endpoint_url", ""),
            script_path=entry.get("script_path", "tool.py"),
            endpoint_auth_header=entry.get("endpoint_auth_header", ""),
            model_name=entry.get("model_name", ""),
            enabled=entry.get("enabled", True),
            origin=entry.get("origin", "imported"),
            source_path=entry.get("source_path", ""),
            version=entry.get("version", ""),
            license=entry.get("license", ""),
            display_name_i18n=dict(entry.get("display_name_i18n") or {}),
            created_at=entry.get("created_at", ""),
            updated_at=entry.get("updated_at", ""),
        )

    async def list(self) -> list[Tool]:
        await self._ensure_loaded()
        out: list[Tool] = []
        for entry in self._entries.values():
            out.append(self._hydrate(entry))
        # Most-recently-updated first; ties on slug for stability.
        out.sort(
            key=lambda t: (
                -(0 if (t.updated_at or t.created_at) == "" else 1),
                t.updated_at or t.created_at or "",
                t.slug,
            )
        )
        return out

    async def get(self, slug: str) -> Tool | None:
        await self._ensure_loaded()
        entry = self._entries.get(slug)
        if entry is None:
            return None
        return self._hydrate(entry)

    async def get_by_model_name(self, model_name: str) -> Tool | None:
        """Resolve a tool by the name the LLM sees (model_name).
        Falls back to slug, then to a scan across stored entries'
        custom model_names. The chat handler uses this when the
        LLM echoes back ``function.name`` from its tool call."""
        if not model_name:
            return None
        if (t := await self.get(model_name)) is not None:
            return t
        for entry in self._entries.values():
            if entry.get("model_name", "").strip() == model_name:
                return self._hydrate(entry)
        return None

    async def get_callable(self, slug: str):
        """Return the Python callable for a local tool, or ``None``
        for script / remote kinds. Used by the chat handler when it
        builds the StreamingTool."""
        entry = self._entries.get(slug)
        if entry is None:
            return None
        if entry.get("kind") == "local":
            # Imported local tools store their callable via the
            # import flow in :mod:`tools.imports`; we look it up
            # from a process-local cache so we don't re-import on
            # every chat call.
            from mhc_desktop_backend.tools.imports import get_cached_local

            return get_cached_local(slug)
        return None

    async def create(self, data: dict[str, Any]) -> Tool:
        await self._ensure_loaded()
        slug = (data.get("slug") or slugify(data.get("name", ""))).strip()
        if not slug:
            raise ToolStoreError("tool slug is required")
        if slug in self._entries:
            raise ToolStoreError(f"tool '{slug}' already exists")

        now = now_iso()
        # Generate the system UUID up front so the response payload
        # carries it from the first call. The slug is for URLs /
        # paths; the id is the immutable system key.
        tool_id = str(uuid.uuid4())
        tool = Tool(
            id=tool_id,
            slug=slug,
            name=data.get("name") or slug,
            description=data.get("description", ""),
            kind=data.get("kind", "local"),
            parameters=data.get("parameters") or {},
            endpoint_url=data.get("endpoint_url", ""),
            script_path=data.get("script_path", "tool.py"),
            endpoint_auth_header=data.get("endpoint_auth_header", ""),
            model_name=data.get("model_name", ""),
            enabled=data.get("enabled", True),
            origin=data.get("origin", "imported"),
            source_path=data.get("source_path", ""),
            version=data.get("version", ""),
            license=data.get("license", ""),
            display_name_i18n=dict(data.get("display_name_i18n") or {}),
            created_at=now,
            updated_at=now,
        )
        async with self._write_lock:
            self._entries[slug] = tool.to_dict()
            self._persist()
        return tool

    async def update(self, slug: str, data: dict[str, Any]) -> Tool:
        await self._ensure_loaded()
        entry = self._entries.get(slug)
        if entry is None:
            raise ToolStoreError(f"tool '{slug}' not found")
        for key in (
            "name",
            "description",
            "kind",
            "parameters",
            "endpoint_url",
            "script_path",
            "endpoint_auth_header",
            "model_name",
            "enabled",
            "version",
            "license",
            "origin",
            "display_name_i18n",
        ):
            if key in data:
                entry[key] = data[key]
        entry["updated_at"] = now_iso()
        async with self._write_lock:
            self._entries[slug] = entry
            self._persist()
        return self._hydrate(entry)

    async def delete(self, slug: str) -> None:
        await self._ensure_loaded()
        if slug not in self._entries:
            return
        del self._entries[slug]
        async with self._write_lock:
            self._persist()
        # Drop the cached callable so a re-import picks up the new code.
        from mhc_desktop_backend.tools.imports import evict_cached_local

        evict_cached_local(slug)

    async def set_enabled(self, slug: str, enabled: bool) -> Tool:
        return await self.update(slug, {"enabled": bool(enabled)})

    async def close(self) -> None:
        self._entries.clear()
        self._loaded = False
