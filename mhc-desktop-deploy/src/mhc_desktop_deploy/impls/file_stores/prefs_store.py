"""File-backed global user preferences store.

A small JSON file at ``~/.mhc-desktop/prefs.json`` holding settings that
are global across every chat session — the user's own additions to the
system prompt is the only field today, but the container is shaped to
take more. Schema is forward-compatible (unknown keys are preserved).

Why a JSON file and not a database / not localStorage:

* Same lifecycle as providers.json / sessions-state.json — one file
  per user, easy to inspect, diff, back up, sync.
* Read once at startup (then cached) and written under a write lock.
* Survives Electron reload / reinstall; the user does not retype.

The store deliberately does not own the BASE system prompt — that's a
system constant owned by the chat router. This file is *only* the
user-authored addition that gets appended to it.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mhc_desktop_deploy.impls.file_stores.paths import PREFS_FILE

logger = logging.getLogger("mhc_desktop_backend")


@dataclass
class Prefs:
    """Single user-scoped preferences record.

    Fields default to empty so a fresh install has a usable object
    without writing a file. Unknown keys round-trip through ``extra``
    so adding a new field on the server doesn't drop user data.
    """

    system_prompt_addition: str = ""
    updated_at: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # ``extra`` may be empty — drop it so the JSON stays minimal.
        if not d["extra"]:
            d.pop("extra")
        return d


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


class PrefsStore:
    """Manage ``prefs.json`` on disk.

    The whole record is read on every call (it's tiny) and written under
    a write lock to keep concurrent updates atomic.
    """

    def __init__(self, prefs_file: Path | None = None) -> None:
        self._file = prefs_file or PREFS_FILE
        self._write_lock = asyncio.Lock()

    async def get(self) -> Prefs:
        if not self._file.exists():
            return Prefs()
        try:
            raw = json.loads(self._file.read_text("utf-8"))
        except json.JSONDecodeError:
            logger.warning("corrupt %s — ignoring", file_path(self._file))
            return Prefs()
        return _parse(raw)

    async def update(self, *, system_prompt_addition: str | None = None) -> Prefs:
        """Merge the supplied fields into the existing record.

        Passing ``None`` leaves a field untouched. Empty string is a
        valid value (it clears the user's addition).
        """
        async with self._write_lock:
            # Same fall-back as get(): a broken file must not brick
            # the app — start from defaults so the next save overwrites
            # the bad bytes.
            current = Prefs()
            if self._file.exists():
                try:
                    current = _parse(json.loads(self._file.read_text("utf-8")))
                except json.JSONDecodeError:
                    logger.warning(
                        "corrupt %s on update; rewriting from defaults",
                        self._file,
                    )
            if system_prompt_addition is not None:
                # Strip on the way in so we don't store trailing whitespace
                # the user can't see in the editor.
                current.system_prompt_addition = system_prompt_addition.strip()
            current.updated_at = now_iso()
            self._file.parent.mkdir(parents=True, exist_ok=True)
            self._file.write_text(
                json.dumps(current.to_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            return current


def _parse(raw: dict[str, Any]) -> Prefs:
    """Build a Prefs from a raw JSON dict.

    Unknown keys go into ``extra`` so they survive a server-side schema
    upgrade without being silently dropped.
    """
    known = {"system_prompt_addition", "updated_at"}
    extra = {k: v for k, v in raw.items() if k not in known}
    return Prefs(
        system_prompt_addition=str(raw.get("system_prompt_addition", "") or ""),
        updated_at=str(raw.get("updated_at", "") or ""),
        extra=extra,
    )


def file_path(p: Path) -> str:
    """Compatibility shim — log helper that uses the file as a string."""
    return str(p)
