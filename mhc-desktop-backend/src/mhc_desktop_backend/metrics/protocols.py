"""Protocol contract for usage-metrics storage.

The dashboard talks to anything that satisfies this protocol. The
default file-backed implementation (JSONL on disk) lives in
:mod:`mhc_desktop_backend.storage.metrics_store`; enterprise
adapters plug in their own (Postgres, Clickhouse, ...) by passing
an object matching the surface to
:func:`mhc_desktop_backend.app.create_app`.

Query methods are intentionally narrow — scalar summary for the
top cards, server-side paginated ranking (full list, never a
fixed top-N), and daily time series for the charts. Heavy
lifting is pushed into the backend so the dashboard never pulls
a full raw log over the wire.

Why ``@runtime_checkable``
--------------------------

Three reasons, matching the rest of :mod:`mhc_desktop_backend.protocols`:

1. FastAPI's dependency-injection ``get_*`` helpers can assert
   ``isinstance(repo, MetricsRepositoryProtocol)`` at the top of
   each route handler — failing fast in tests beats a confusing 500.
2. Health-check / startup probes can confirm the wired adapter
   actually conforms (catches accidentally passing ``None``).
3. External monitoring / test harnesses get the same answer
   without importing the concrete classes.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from mhc_desktop_backend.metrics.types import (
    LLMCallRecord,
    ToolCallRecord,
    RankingPage,
    SummaryBucket,
    TrendPoint,
)

RANKING_KIND_TOOLS = "tools"
RANKING_KIND_SKILLS = "skills"
RANKING_KIND_MCPS = "mcps"
RANKING_KIND_MODELS = "models"

RANKING_KINDS: tuple[str, ...] = (
    RANKING_KIND_TOOLS,
    RANKING_KIND_SKILLS,
    RANKING_KIND_MCPS,
    RANKING_KIND_MODELS,
)


@runtime_checkable
class MetricsRepositoryProtocol(Protocol):
    """Persistent storage for usage metrics.

    ``date_from`` / ``date_to`` are inclusive ``YYYY-MM-DD``
    strings (UTC day boundaries; the API layer converts local
    "today" to UTC). When both are ``None``, the query covers
    every recorded event.

    ``query_ranking`` must apply pagination **itself** (slice or
    ``LIMIT``/``OFFSET``) — the dashboard never fetches a full
    ranking from the backend. ``query_trend`` returns one
    :class:`TrendPoint` per day in the requested range,
    zero-filled for days without events.

    ``conversation_count_by_day`` (when supplied by the API
    layer) is the per-day count of chat sessions — the session
    store is the source of truth for "did a conversation happen
    today?", independent of whether the LLM was reached.
    """

    async def record_llm_call(self, record: LLMCallRecord) -> None: ...
    async def record_tool_call(self, record: ToolCallRecord) -> None: ...
    async def query_summary(
        self,
        date_from: str | None = None,
        date_to: str | None = None,
        *,
        conversation_count_by_day: dict[str, int] | None = None,
    ) -> SummaryBucket: ...
    async def query_ranking(
        self,
        kind: str,
        date_from: str | None = None,
        date_to: str | None = None,
        page: int = 1,
        page_size: int = 10,
    ) -> RankingPage: ...
    async def query_trend(
        self,
        date_from: str | None = None,
        date_to: str | None = None,
        *,
        conversation_count_by_day: dict[str, int] | None = None,
    ) -> list[TrendPoint]: ...
    async def close(self) -> None: ...


__all__ = [
    "MetricsRepositoryProtocol",
    "RANKING_KIND_TOOLS",
    "RANKING_KIND_SKILLS",
    "RANKING_KIND_MCPS",
    "RANKING_KIND_MODELS",
    "RANKING_KINDS",
]
