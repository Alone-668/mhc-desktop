"""File-backed usage-metrics repository (JSONL).

Each event (LLM call, tool call) is appended as one JSON line to
``metrics.jsonl`` under the user data dir. Queries scan the file
and aggregate in memory — acceptable for the single-user local
variant.

Why JSONL and not SQLite
------------------------

* The store is write-mostly (one write per LLM/tool call) and
  read-on-demand (dashboard load). JSONL appends are O(1) and
  survive power loss cleanly.
* The expected volume is small — a heavy user makes maybe a few
  thousand calls per day. A single JSONL file is easy to inspect,
  diff, back up, and grep.
* Switching to SQLite or Postgres is a future change to the
  concrete impl only — the protocol surface in
  :mod:`mhc_desktop_backend.metrics.protocols` stays identical.

Corrupt-line behaviour
----------------------

``json.loads`` raising on a single bad line must NOT kill the
whole dashboard. We log + skip and keep going — the alternative
(a single dropped record bricking every subsequent query) is
strictly worse than a small accuracy loss.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

from mhc_desktop_backend.metrics.aggregations import (
    aggregate_summary,
    aggregate_trend,
    paginate,
    rank_items,
)
from mhc_desktop_backend.metrics.protocols import (
    RANKING_KIND_MCPS,
    RANKING_KIND_MODELS,
    RANKING_KIND_SKILLS,
    RANKING_KIND_TOOLS,
)
from mhc_desktop_backend.metrics.types import (
    LLMCallRecord,
    RankingPage,
    SummaryBucket,
    ToolCallRecord,
    TrendPoint,
)

from mhc_desktop_deploy.impls.file_stores.paths import METRICS_FILE

logger = logging.getLogger("mhc_desktop_backend")


# Field sets the on-disk JSONL should keep when non-empty. We drop
# fields at their default (empty string / False / None) to keep the
# file compact, while always keeping the discriminator fields so
# replay / debug tools can read it back without guessing.
_LLM_REQUIRED = ("ts", "session_id", "provider", "model", "status")
_TOOL_REQUIRED = ("ts", "session_id", "kind", "name", "status")


class JSONLMetricsRepository:
    """File-backed :class:`MetricsRepositoryProtocol` for the desktop variant.

    Append writes are guarded by a process-local lock — the chat
    handler can fire from multiple asyncio tasks concurrently. The
    lock is not shared across processes; mhc-desktop is
    single-process by design.

    Implements :class:`MetricsRepositoryProtocol` structurally — no
    inheritance. ``isinstance(repo, MetricsRepositoryProtocol)``
    passes thanks to ``@runtime_checkable`` on the Protocol.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._file = path or METRICS_FILE
        self._write_lock = threading.Lock()

    # ── Write ────────────────────────────────────────────────────────────────

    def _append(self, entry: dict[str, Any]) -> None:
        with self._write_lock:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    @staticmethod
    def _llm_to_json(record: LLMCallRecord) -> dict[str, Any]:
        d: dict[str, Any] = {"type": "llm"}
        for k in LLMCallRecord.__dataclass_fields__:
            v = getattr(record, k)
            if k in _LLM_REQUIRED:
                d[k] = v
            elif isinstance(v, bool):
                # Booleans: keep ``True`` (e.g. cancelled), drop False.
                if v:
                    d[k] = v
            elif v not in (None, ""):
                d[k] = v
        return d

    @staticmethod
    def _tool_to_json(record: ToolCallRecord) -> dict[str, Any]:
        d: dict[str, Any] = {"type": "tool"}
        for k in ToolCallRecord.__dataclass_fields__:
            v = getattr(record, k)
            if k in _TOOL_REQUIRED:
                d[k] = v
            elif isinstance(v, bool):
                if v:
                    d[k] = v
            elif v not in (None, ""):
                d[k] = v
        return d

    async def record_llm_call(self, record: LLMCallRecord) -> None:
        try:
            self._append(self._llm_to_json(record))
        except Exception:
            # A failure to record metrics must NOT crash the chat
            # handler — surface in logs, swallow, keep going.
            logger.exception("metrics.record_llm.failed")

    async def record_tool_call(self, record: ToolCallRecord) -> None:
        try:
            self._append(self._tool_to_json(record))
        except Exception:
            logger.exception("metrics.record_tool.failed")

    # ── Read ─────────────────────────────────────────────────────────────────

    def _iter_records(
        self,
    ) -> tuple[list[LLMCallRecord], list[ToolCallRecord]]:
        if not self._file.exists():
            return [], []
        llm: list[LLMCallRecord] = []
        tools: list[ToolCallRecord] = []
        with open(self._file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning("metrics.skip_corrupt_line preview=%.120s", line)
                    continue
                rtype = data.get("type")
                if rtype == "tool":
                    tools.append(
                        ToolCallRecord(
                            ts=str(data.get("ts", "")),
                            session_id=str(data.get("session_id", "")),
                            kind=str(data.get("kind", "tool")),
                            name=str(data.get("name", "")),
                            user_id=str(data.get("user_id", "")),
                            duration_ms=float(data.get("duration_ms") or 0.0),
                            status=str(data.get("status", "ok")),
                            error=str(data.get("error", "")),
                        )
                    )
                elif rtype == "llm":
                    llm.append(
                        LLMCallRecord(
                            ts=str(data.get("ts", "")),
                            session_id=str(data.get("session_id", "")),
                            provider=str(data.get("provider", "")),
                            model=str(data.get("model", "")),
                            prompt_tokens=int(data.get("prompt_tokens") or 0),
                            completion_tokens=int(data.get("completion_tokens") or 0),
                            duration_ms=float(data.get("duration_ms") or 0.0),
                            user_id=str(data.get("user_id", "")),
                            status=str(data.get("status", "ok")),
                            error=str(data.get("error", "")),
                            cancelled=bool(data.get("cancelled", False)),
                        )
                    )
        return llm, tools

    async def query_summary(
        self,
        date_from: str | None = None,
        date_to: str | None = None,
        *,
        user_id: str | None = None,
        conversation_count_by_day: dict[str, int] | None = None,
    ) -> SummaryBucket:
        llm, tools = self._iter_records()
        return aggregate_summary(
            llm,
            tools,
            date_from=date_from,
            date_to=date_to,
            user_id=user_id,
            conversation_count_by_day=conversation_count_by_day,
        )

    async def query_ranking(
        self,
        kind: str,
        date_from: str | None = None,
        date_to: str | None = None,
        page: int = 1,
        page_size: int = 10,
        *,
        user_id: str | None = None,
    ) -> RankingPage:
        if kind not in (
            RANKING_KIND_TOOLS,
            RANKING_KIND_SKILLS,
            RANKING_KIND_MCPS,
            RANKING_KIND_MODELS,
        ):
            raise ValueError(f"unknown ranking kind: {kind!r}")
        llm, tools = self._iter_records()
        items = rank_items(
            kind, llm, tools, date_from=date_from, date_to=date_to, user_id=user_id
        )
        return paginate(items, page, page_size)

    async def query_trend(
        self,
        date_from: str | None = None,
        date_to: str | None = None,
        *,
        user_id: str | None = None,
        conversation_count_by_day: dict[str, int] | None = None,
    ) -> list[TrendPoint]:
        llm, tools = self._iter_records()
        return aggregate_trend(
            llm,
            tools,
            date_from=date_from,
            date_to=date_to,
            user_id=user_id,
            conversation_count_by_day=conversation_count_by_day,
        )

    async def close(self) -> None:
        return None


# In-memory reference / test double, mirrors the JSONL repo's
# public surface so the same tests cover both backends. Kept here
# (not in metrics.protocols) because it isn't part of the
# protocol — deployments don't need to depend on it.
class InMemoryMetricsRepository:
    """Thread-safe in-memory :class:`MetricsRepositoryProtocol`.

    Lives next to the JSONL implementation so the protocol layer
    stays free of test doubles. Useful for unit tests where
    hitting the disk would slow things down.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._llm: list[LLMCallRecord] = []
        self._tools: list[ToolCallRecord] = []

    async def record_llm_call(self, record: LLMCallRecord) -> None:
        with self._lock:
            self._llm.append(record)

    async def record_tool_call(self, record: ToolCallRecord) -> None:
        with self._lock:
            self._tools.append(record)

    async def query_summary(
        self,
        date_from: str | None = None,
        date_to: str | None = None,
        *,
        user_id: str | None = None,
        conversation_count_by_day: dict[str, int] | None = None,
    ) -> SummaryBucket:
        with self._lock:
            llm = list(self._llm)
            tools = list(self._tools)
        return aggregate_summary(
            llm,
            tools,
            date_from=date_from,
            date_to=date_to,
            user_id=user_id,
            conversation_count_by_day=conversation_count_by_day,
        )

    async def query_ranking(
        self,
        kind: str,
        date_from: str | None = None,
        date_to: str | None = None,
        page: int = 1,
        page_size: int = 10,
        *,
        user_id: str | None = None,
    ) -> RankingPage:
        if kind not in (
            RANKING_KIND_TOOLS,
            RANKING_KIND_SKILLS,
            RANKING_KIND_MCPS,
            RANKING_KIND_MODELS,
        ):
            raise ValueError(f"unknown ranking kind: {kind!r}")
        with self._lock:
            llm = list(self._llm)
            tools = list(self._tools)
        items = rank_items(
            kind, llm, tools, date_from=date_from, date_to=date_to, user_id=user_id
        )
        return paginate(items, page, page_size)

    async def query_trend(
        self,
        date_from: str | None = None,
        date_to: str | None = None,
        *,
        user_id: str | None = None,
        conversation_count_by_day: dict[str, int] | None = None,
    ) -> list[TrendPoint]:
        with self._lock:
            llm = list(self._llm)
            tools = list(self._tools)
        return aggregate_trend(
            llm,
            tools,
            date_from=date_from,
            date_to=date_to,
            user_id=user_id,
            conversation_count_by_day=conversation_count_by_day,
        )

    async def close(self) -> None:
        return None


__all__ = [
    "InMemoryMetricsRepository",
    "JSONLMetricsRepository",
]
