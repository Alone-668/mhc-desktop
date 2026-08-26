"""File-backed chat session store.

Each session lives at ``~/.mhc-desktop/sessions/<id>.json`` as a single
JSON object::

    {
      "id": "uuid",
      "title": "first user message",
      "messages": [{"role": "user", "content": "..."}, ...],
      "provider": "openai",
      "model": "gpt-4o-mini",
      "created_at": "ISO",
      "updated_at": "ISO"
    }

The system prompt lives in a global ``prefs.json`` (see
:mod:`mhc_desktop_backend.storage.prefs_store`) and is assembled by
the chat router at request time — it is intentionally NOT stored on
each session, both because it's cross-session and because storing a
multi-KB prompt on every message turn would be wasteful.

A lightweight index file (``sessions/index.json``) holds the list shape
used by ``GET /api/v1/sessions`` (id, title, updated_at) so we don't
have to walk every file just to render the sidebar. The index is
re-written on every mutation, accepting the small write cost for
fewer filesystem scans.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mhc_desktop_deploy.impls.file_stores.paths import SESSIONS_DIR

logger = logging.getLogger("mhc_desktop_backend")


@dataclass
class Session:
    id: str
    title: str = "New chat"
    messages: list[dict[str, Any]] = field(default_factory=list)
    provider: str = ""
    model: str = ""
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def summary(self) -> dict[str, Any]:
        """Compact representation for the sidebar list."""
        return {
            "id": self.id,
            "title": self.title,
            "provider": self.provider,
            "model": self.model,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class SessionStore:
    """Manages sessions on disk with hot reload on mtime change."""

    def __init__(self, sessions_dir: Path | None = None) -> None:
        self._dir = sessions_dir or SESSIONS_DIR
        self._index_path = self._dir / "index.json"
        self._sessions: dict[str, Session] = {}
        self._loaded = False
        self._mtime: int | None = None
        self._write_lock = asyncio.Lock()

    def _index_mtime(self) -> int | None:
        try:
            return self._index_path.stat().st_mtime_ns
        except OSError:
            return None

    async def _ensure_loaded(self) -> None:
        mtime = self._index_mtime()
        if self._loaded and mtime == self._mtime:
            return
        self._sessions = {}
        if self._index_path.exists():
            try:
                raw = json.loads(self._index_path.read_text("utf-8"))
            except json.JSONDecodeError:
                logger.exception("corrupt %s — ignoring", self._index_path)
                raw = []
            for entry in raw or []:
                sid = entry.get("id")
                if not sid:
                    continue
                self._sessions[sid] = Session(
                    id=sid,
                    title=entry.get("title", ""),
                    messages=[],
                    provider=entry.get("provider", ""),
                    model=entry.get("model", ""),
                    created_at=entry.get("created_at", ""),
                    updated_at=entry.get("updated_at", ""),
                )
        self._mtime = mtime
        self._loaded = True

    def _session_path(self, sid: str) -> Path:
        return self._dir / f"{sid}.json"

    def _load_full(self, sid: str) -> Session | None:
        path = self._session_path(sid)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text("utf-8"))
        except json.JSONDecodeError:
            logger.exception("corrupt session %s", path)
            return None
        return Session(
            id=data.get("id", sid),
            title=data.get("title", ""),
            messages=list(data.get("messages", [])),
            provider=data.get("provider", ""),
            model=data.get("model", ""),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )

    def _persist(self, sess: Session) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        self._session_path(sess.id).write_text(
            json.dumps(sess.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        index_data = [
            {
                "id": s.id,
                "title": s.title,
                "provider": s.provider,
                "model": s.model,
                "created_at": s.created_at,
                "updated_at": s.updated_at,
            }
            for s in self._sessions.values()
        ]
        self._index_path.write_text(
            json.dumps(index_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        self._mtime = self._index_mtime()

    async def list(self) -> list[Session]:
        await self._ensure_loaded()
        # Most recent first
        return sorted(
            self._sessions.values(),
            key=lambda s: s.updated_at or s.created_at or "",
            reverse=True,
        )

    async def get(self, sid: str) -> Session | None:
        await self._ensure_loaded()
        if sid not in self._sessions:
            return None
        return self._load_full(sid) or self._sessions[sid]

    async def create(self, data: dict[str, Any] | None = None) -> Session:
        await self._ensure_loaded()
        data = data or {}
        now = datetime.now(UTC).isoformat()
        sid = data.get("id") or str(uuid.uuid4())
        sess = Session(
            id=sid,
            title=data.get("title") or "New chat",
            messages=list(data.get("messages") or []),
            provider=data.get("provider") or "",
            model=data.get("model") or "",
            created_at=now,
            updated_at=now,
        )
        async with self._write_lock:
            self._sessions[sid] = sess
            self._persist(sess)
        return sess

    async def update(self, sid: str, data: dict[str, Any]) -> Session:
        await self._ensure_loaded()
        existing = await self.get(sid)
        if existing is None:
            raise ValueError(f"session '{sid}' not found")
        for key in ("title", "messages", "provider", "model"):
            if key in data:
                setattr(existing, key, data[key])
        existing.updated_at = datetime.now(UTC).isoformat()
        if not existing.title and existing.messages:
            user_msgs = [m for m in existing.messages if m.get("role") == "user"]
            if user_msgs:
                first = str(user_msgs[0].get("content", ""))[:60]
                existing.title = first.strip() or "New chat"
        async with self._write_lock:
            self._sessions[sid] = existing
            self._persist(existing)
        return existing

    async def delete(self, sid: str) -> None:
        await self._ensure_loaded()
        if sid not in self._sessions:
            return
        path = self._session_path(sid)
        if path.exists():
            path.unlink()
        del self._sessions[sid]
        async with self._write_lock:
            self._mtime = None  # invalidate cache
            # Refresh index
            index_data = [
                {
                    "id": s.id,
                    "title": s.title,
                    "provider": s.provider,
                    "model": s.model,
                    "created_at": s.created_at,
                    "updated_at": s.updated_at,
                }
                for s in self._sessions.values()
            ]
            self._index_path.write_text(
                json.dumps(index_data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            self._mtime = self._index_mtime()

    async def delete_many(self, sids: list[str]) -> int:
        """Delete several sessions in one transaction. Returns the number actually removed."""
        await self._ensure_loaded()
        if not sids:
            return 0
        unique = [s for s in dict.fromkeys(sids) if s in self._sessions]
        if not unique:
            return 0
        for sid in unique:
            path = self._session_path(sid)
            if path.exists():
                path.unlink()
            del self._sessions[sid]
        async with self._write_lock:
            index_data = [
                {
                    "id": s.id,
                    "title": s.title,
                    "provider": s.provider,
                    "model": s.model,
                    "created_at": s.created_at,
                    "updated_at": s.updated_at,
                }
                for s in self._sessions.values()
            ]
            self._index_path.write_text(
                json.dumps(index_data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            self._mtime = self._index_mtime()
        return len(unique)

    async def clear_all(self) -> int:
        """Delete every session on disk. Returns the number removed."""
        await self._ensure_loaded()
        all_ids = list(self._sessions.keys())
        if not all_ids:
            return 0
        for sid in all_ids:
            path = self._session_path(sid)
            if path.exists():
                path.unlink()
        self._sessions.clear()
        async with self._write_lock:
            self._index_path.write_text("[]", encoding="utf-8")
            self._mtime = self._index_mtime()
        return len(all_ids)

    async def close(self) -> None:
        self._sessions.clear()
        self._loaded = False

    async def count_by_day(
        self,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict[str, int]:
        """Return {YYYY-MM-DD: count} of sessions created in [date_from, date_to].

        Both bounds are inclusive ``YYYY-MM-DD`` strings (UTC day
        boundaries). ``None`` bounds are open-ended. Used by the
        metrics dashboard to attach conversation counts to the
        summary / trend without the metrics store having to know
        about session shape.

        Sessions whose ``created_at`` is missing or unparseable are
        silently dropped — they cannot be bucketed into a day and
        would otherwise inflate / corrupt the chart.
        """
        await self._ensure_loaded()
        out: dict[str, int] = {}
        for s in self._sessions.values():
            created = s.created_at or ""
            day = created[:10]
            if not day or len(day) != 10:
                continue
            if date_from and day < date_from:
                continue
            if date_to and day > date_to:
                continue
            out[day] = out.get(day, 0) + 1
        return out
