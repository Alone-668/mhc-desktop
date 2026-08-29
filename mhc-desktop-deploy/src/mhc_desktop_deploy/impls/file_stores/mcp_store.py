"""MCP server store.

Layout under ``~/.mhc-desktop/``::

    mcp-state.json                  # {slug: {enabled, origin, source_path, ...}}
    mcp/<slug>/
      config.json                    # MCPServer.to_dict() minus runtime fields
      log/                           # last-N lines of subprocess stderr (debug)

The state file keeps user toggles and origin outside the per-server
folder so re-importing doesn't clobber them. The config file is
what the manager actually reads when spawning.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

from mhc_desktop_backend.mcp.manager import MCPError
from mhc_desktop_backend.mcp.models import MCPServer, now_iso, slugify

logger = logging.getLogger("mhc_desktop_backend")

__all__ = ["MCPStore"]


# ``MCPError`` is imported from the kernel — see
# :mod:`mhc_desktop_backend.mcp.manager`. We re-export it on this
# module's namespace so existing ``from ...mcp.store import MCPError``
# callers keep working.


class MCPStore:
    """Manage MCP servers on disk."""

    def __init__(
        self,
        mcp_dir: Path | None = None,
        state_file: Path | None = None,
    ) -> None:
        from mhc_desktop_deploy.impls.file_stores.paths import MCP_DIR, MCP_STATE_FILE

        self._dir = mcp_dir or MCP_DIR
        self._state_file = state_file or MCP_STATE_FILE
        self._write_lock = asyncio.Lock()
        self._dir.mkdir(parents=True, exist_ok=True)

    # ── Public API ──────────────────────────────────────────────────

    async def list(self) -> list[MCPServer]:
        state = self._load_state()
        out: list[MCPServer] = []
        for child in sorted(self._dir.iterdir()):
            if not child.is_dir():
                continue
            try:
                srv = await self._read_server(child, state)
            except Exception:
                logger.exception("failed to read MCP dir %s", child)
                continue
            out.append(srv)
        return out

    async def get(self, slug: str) -> MCPServer | None:
        path = self._dir / slug
        if not path.is_dir():
            return None
        state = self._load_state()
        try:
            return await self._read_server(path, state)
        except Exception as e:
            raise MCPError(f"failed to read MCP '{slug}': {e}") from e

    async def upsert(
        self,
        *,
        slug: str,
        name: str,
        description: str,
        command: str,
        args: list[str],
        env: dict[str, str] | None = None,
        origin: str = "imported",
        display_name_i18n: dict[str, str] | None = None,
    ) -> MCPServer:
        """Create or update an MCP server spec."""
        if not command.strip():
            raise MCPError("command must not be empty")
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            raise MCPError("args must be a list of strings")
        env = env or {}
        if not isinstance(env, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in env.items()
        ):
            raise MCPError("env must be a dict of string -> string")
        final_slug = slugify(slug or name)
        if not final_slug:
            raise MCPError("slug must not be empty")

        target = self._dir / final_slug
        async with self._write_lock:
            existing = await self.get(final_slug)
            now = now_iso()
            if existing is None:
                server = MCPServer(
                    id=str(uuid.uuid4()),
                    slug=final_slug,
                    name=name or final_slug,
                    description=description,
                    command=command,
                    args=list(args),
                    env=dict(env),
                    enabled=True,
                    origin=origin,
                    display_name_i18n=dict(display_name_i18n or {}),
                    created_at=now,
                    updated_at=now,
                )
            else:
                # Merge: keep the existing tools / last_connected_at /
                # last_error from the state file so a config edit doesn't
                # blow away runtime discovery state.
                # Display-name locales: caller-supplied wins when
                # provided, otherwise preserve the existing entry.
                i18n = (
                    dict(display_name_i18n)
                    if display_name_i18n is not None
                    else dict(existing.display_name_i18n)
                )
                server = MCPServer(
                    id=existing.id or str(uuid.uuid4()),
                    slug=existing.slug,
                    name=name or existing.name,
                    description=description,
                    command=command,
                    args=list(args),
                    env=dict(env),
                    enabled=existing.enabled,
                    origin=existing.origin,
                    display_name_i18n=i18n,
                    tools=list(existing.tools),
                    last_connected_at=existing.last_connected_at,
                    last_error=existing.last_error,
                    created_at=existing.created_at or now,
                    updated_at=now,
                )
            target.mkdir(parents=True, exist_ok=True)
            self._write_config(target, server)
            state = self._load_state()
            entry = state.setdefault(final_slug, {})
            entry.update(
                {
                    "enabled": server.enabled,
                    "origin": server.origin,
                    "source_path": server.source_path,
                    "created_at": server.created_at,
                    "updated_at": server.updated_at,
                }
            )
            self._save_state(state)
        return server

    async def delete(self, slug: str) -> None:
        path = self._dir / slug
        async with self._write_lock:
            if path.is_dir():
                shutil.rmtree(path)
            state = self._load_state()
            state.pop(slug, None)
            self._save_state(state)

    async def set_enabled(self, slug: str, enabled: bool) -> MCPServer:
        async with self._write_lock:
            srv = await self.get(slug)
            if srv is None:
                raise MCPError(f"MCP '{slug}' not found")
            srv.enabled = enabled
            srv.updated_at = now_iso()
            self._write_config(self._dir / slug, srv)
            state = self._load_state()
            entry = state.setdefault(slug, {})
            entry["enabled"] = enabled
            entry["updated_at"] = srv.updated_at
            self._save_state(state)
        return srv

    async def record_discovery(
        self,
        slug: str,
        tools: list[dict[str, Any]],
        *,
        error: str = "",
    ) -> None:
        """Persist the result of a ``tools/list`` call so the management
        page can show what each MCP exposes without reconnecting."""
        async with self._write_lock:
            srv = await self.get(slug)
            if srv is None:
                return
            srv.tools = list(tools)
            srv.last_connected_at = now_iso() if not error else srv.last_connected_at
            srv.last_error = error
            srv.updated_at = srv.last_connected_at or srv.updated_at
            self._write_config(self._dir / slug, srv)
            state = self._load_state()
            entry = state.setdefault(slug, {})
            entry["last_connected_at"] = srv.last_connected_at
            entry["last_error"] = srv.last_error
            self._save_state(state)

    # ── Internal helpers ────────────────────────────────────────────

    async def _read_server(self, path: Path, state: dict[str, Any]) -> MCPServer:
        cfg_path = path / "config.json"
        if not cfg_path.is_file():
            raise MCPError(f"MCP dir {path} is missing config.json")
        data = json.loads(cfg_path.read_text("utf-8"))
        entry = state.get(path.name, {})
        s = MCPServer(
            slug=path.name,
            id=entry.get("id", data.get("id", "")),
            name=data.get("name", path.name),
            description=data.get("description", ""),
            command=data.get("command", ""),
            args=list(data.get("args") or []),
            env=dict(data.get("env") or {}),
            enabled=bool(entry.get("enabled", data.get("enabled", True))),
            origin=entry.get("origin", data.get("origin", "imported")),
            source_path=entry.get("source_path", ""),
            display_name_i18n=dict(data.get("display_name_i18n") or {}),
            tools=list(data.get("tools") or []),
            last_connected_at=entry.get(
                "last_connected_at", data.get("last_connected_at", "")
            ),
            last_error=entry.get("last_error", data.get("last_error", "")),
            created_at=entry.get("created_at", data.get("created_at", "")),
            updated_at=entry.get("updated_at", data.get("updated_at", "")),
        )
        # Backfill UUID if loading an older record that lacks one.
        if not s.id:
            s.id = str(uuid.uuid4())
            entry["id"] = s.id
            self._save_state(state)
        return s

    def _write_config(self, path: Path, srv: MCPServer) -> None:
        cfg_path = path / "config.json"
        # Config = everything except the state-file-only fields. The
        # state file is the source of truth for origin / source_path;
        # config.json is the source of truth for the spawn vector and
        # the discovered tool list.
        d = asdict(srv)
        d.pop("origin", None)
        d.pop("source_path", None)
        cfg_path.write_text(
            json.dumps(d, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _load_state(self) -> dict[str, Any]:
        if not self._state_file.exists():
            return {}
        try:
            return json.loads(self._state_file.read_text("utf-8"))
        except json.JSONDecodeError:
            logger.warning("corrupt %s — ignoring", self._state_file)
            return {}

    def _save_state(self, state: dict[str, Any]) -> None:
        self._state_file.write_text(
            json.dumps(state, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    async def close(self) -> None:
        """No-op — file-backed store has no resources to release.

        Defined so the reference impl satisfies
        :class:`mhc_desktop_backend.protocols.MCPStoreProtocol`.
        """
        return
