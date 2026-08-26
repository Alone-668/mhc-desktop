"""File-backed LLM provider configuration store.

Schema is **byte-for-byte compatible with mh-local's** ``providers.json``
so that a user can copy the file between the two apps. Fields follow
the same names as :class:`mh_gateway.llm.LLMProviderConfig` even though
we do not import that class (we deliberately stay independent of
mh-gateway per the project's design rules).
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mhc_desktop_backend.protocol_models import Provider
from mhc_desktop_deploy.impls.file_stores.paths import PROVIDERS_FILE

logger = logging.getLogger("mhc_desktop_backend")

_WRITE_LOCK = asyncio.Lock()


class ProviderStore:
    """File-backed provider registry with hot-reload on mtime change."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or PROVIDERS_FILE
        self._providers: dict[str, Provider] = {}
        self._loaded = False
        self._mtime: int | None = None

    def _file_mtime(self) -> int | None:
        try:
            return self._path.stat().st_mtime_ns
        except OSError:
            return None

    async def _ensure_loaded(self) -> None:
        mtime = self._file_mtime()
        if self._loaded and mtime == self._mtime:
            return
        self._providers = {}
        if self._path.exists():
            try:
                raw = json.loads(self._path.read_text("utf-8"))
            except json.JSONDecodeError:
                logger.exception("Corrupt %s — keeping as empty", self._path)
                raw = []
            for entry in raw or []:
                if isinstance(entry, dict) and entry.get("name"):
                    p = Provider.from_dict(entry)
                    self._providers[p.name] = p
        self._mtime = mtime
        self._loaded = True

    async def _persist(self) -> None:
        async with _WRITE_LOCK:
            payload = [p.to_dict() for p in self._providers.values()]
            self._path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            self._mtime = self._file_mtime()

    async def list(self) -> list[Provider]:
        await self._ensure_loaded()
        return list(self._providers.values())

    async def get(self, name: str) -> Provider | None:
        await self._ensure_loaded()
        return self._providers.get(name)

    async def create(self, data: dict[str, Any]) -> Provider:
        await self._ensure_loaded()
        name = (data.get("name") or "").strip()
        if not name:
            raise ValueError("name is required")
        if name in self._providers:
            raise ValueError(f"provider '{name}' already exists")
        now = datetime.now(UTC).isoformat()
        provider = Provider.from_dict({**data, "name": name})
        provider.created_at = now
        provider.updated_at = now
        self._providers[name] = provider
        await self._persist()
        return provider

    async def update(self, name: str, data: dict[str, Any]) -> Provider:
        await self._ensure_loaded()
        existing = self._providers.get(name)
        if existing is None:
            raise ValueError(f"provider '{name}' not found")
        merged = {**existing.to_dict(), **data, "name": name}
        provider = Provider.from_dict(merged)
        provider.created_at = existing.created_at
        provider.updated_at = datetime.now(UTC).isoformat()
        self._providers[name] = provider
        await self._persist()
        return provider

    async def delete(self, name: str) -> None:
        await self._ensure_loaded()
        if name not in self._providers:
            raise ValueError(f"provider '{name}' not found")
        del self._providers[name]
        await self._persist()

    async def close(self) -> None:
        self._providers.clear()
        self._loaded = False
        self._mtime = None
