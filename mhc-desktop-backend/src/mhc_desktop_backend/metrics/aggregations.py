"""Pure aggregation helpers shared by every backend.

These functions take the raw records (already filtered to the
requested date range by the caller) and return summary / ranking
/ trend shapes. They are storage-agnostic so the same code paths
unit-test with plain lists of dataclasses and run identically on
JSONL / SQLite / Postgres-backed deployments.

Pure-function design — no IO, no globals. Easy to test, easy to
port, easy to reason about.
"""

from __future__ import annotations

from datetime import date, timedelta

from mhc_desktop_backend.metrics.protocols import (
    RANKING_KIND_MCPS,
    RANKING_KIND_MODELS,
    RANKING_KIND_SKILLS,
    RANKING_KIND_TOOLS,
)
from mhc_desktop_backend.metrics.types import (
    LLMCallRecord,
    ToolCallRecord,
    RankedItem,
    RankingPage,
    SummaryBucket,
    TrendPoint,
)


# ── Date helpers ────────────────────────────────────────────────────────────


def _day(ts: str) -> str:
    """Return ``YYYY-MM-DD`` for an ISO timestamp; empty in → empty out."""
    return ts[:10] if ts else ""


def _within(ts: str, date_from: str | None, date_to: str | None) -> bool:
    """Inclusive day-range check. ``None`` bounds are open-ended."""
    d = _day(ts)
    if not d:
        return True
    if date_from and d < date_from:
        return False
    if date_to and d > date_to:
        return False
    return True


def _iter_days(date_from: str, date_to: str) -> list[str]:
    """Inclusive list of ISO dates between ``date_from`` and ``date_to``."""
    try:
        start = date.fromisoformat(date_from)
        end = date.fromisoformat(date_to)
    except ValueError:
        return [date_from]
    days: list[str] = []
    d = start
    while d <= end:
        days.append(d.isoformat())
        d += timedelta(days=1)
    return days


def _percentile(sorted_vals: list[float], pct: float) -> float:
    """Nearest-rank percentile on a pre-sorted list. Empty → 0."""
    if not sorted_vals:
        return 0.0
    idx = min(int(len(sorted_vals) * pct), len(sorted_vals) - 1)
    return sorted_vals[idx]


# ── Summary ─────────────────────────────────────────────────────────────────


def aggregate_summary(
    llm: list[LLMCallRecord],
    tools: list[ToolCallRecord],
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    conversation_count_by_day: dict[str, int] | None = None,
) -> SummaryBucket:
    """Compute the dashboard's top-card metrics.

    ``conversation_count_by_day`` is supplied by the API layer
    from the session store — it is *not* computed from the LLM
    stream (a cancelled-before-anything call still counts as a
    conversation, because the user opened one).
    """
    bucket = SummaryBucket()
    model_durations: dict[tuple[str, str], list[float]] = {}
    model_tokens: dict[tuple[str, str], list[int]] = {}
    total_duration = 0.0

    for r in llm:
        if not _within(r.ts, date_from, date_to):
            continue
        bucket.llm_call_count += 1
        bucket.prompt_tokens += r.prompt_tokens
        bucket.completion_tokens += r.completion_tokens
        total_duration += r.duration_ms
        if r.status == "error":
            bucket.llm_error_count += 1
        key = (r.provider or "unknown", r.model or "unknown")
        model_durations.setdefault(key, []).append(r.duration_ms)
        total_tokens = r.prompt_tokens + r.completion_tokens
        model_tokens.setdefault(key, []).append(total_tokens)

    for r in tools:
        if not _within(r.ts, date_from, date_to):
            continue
        if r.kind == "skill":
            bucket.skill_call_count += 1
        elif r.kind == "mcp":
            bucket.mcp_call_count += 1
        else:
            bucket.tool_call_count += 1
            if r.status == "error":
                bucket.tool_error_count += 1

    bucket.total_tokens = bucket.prompt_tokens + bucket.completion_tokens
    if bucket.llm_call_count:
        bucket.avg_duration_ms = total_duration / bucket.llm_call_count
        bucket.error_rate = bucket.llm_error_count / bucket.llm_call_count
        bucket.avg_tokens_per_call = bucket.total_tokens / bucket.llm_call_count

    if conversation_count_by_day:
        for day, count in conversation_count_by_day.items():
            # Day strings are ``YYYY-MM-DD``; synthesize a UTC midnight
            # timestamp so ``_within`` matches against the same range.
            if _within(day + "T00:00:00Z", date_from, date_to):
                bucket.conversation_count += count

    for (provider, model), durs in model_durations.items():
        n = len(durs)
        sorted_d = sorted(durs)
        tokens = model_tokens[(provider, model)]
        avg_tokens = sum(tokens) / n if n else 0.0
        bucket.model_perf.append(
            {
                "provider": provider,
                "model": model,
                "call_count": n,
                "avg_duration_ms": round(sum(durs) / n, 2),
                "avg_tokens": round(avg_tokens, 2),
                "p50_ms": round(_percentile(sorted_d, 0.50), 2),
                "p95_ms": round(_percentile(sorted_d, 0.95), 2),
                "p99_ms": round(_percentile(sorted_d, 0.99), 2),
            }
        )
    bucket.model_perf.sort(key=lambda m: -m["call_count"])
    return bucket


# ── Ranking ─────────────────────────────────────────────────────────────────


def rank_items(
    kind: str,
    llm: list[LLMCallRecord],
    tools: list[ToolCallRecord],
    *,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[RankedItem]:
    """Return the full (un-paginated) ranking for one kind."""
    if kind == RANKING_KIND_TOOLS:
        return _rank_by_kind("tool", tools, date_from, date_to)
    if kind == RANKING_KIND_SKILLS:
        return _rank_by_kind("skill", tools, date_from, date_to)
    if kind == RANKING_KIND_MCPS:
        return _rank_by_kind("mcp", tools, date_from, date_to)
    if kind == RANKING_KIND_MODELS:
        return _rank_models(llm, date_from, date_to)
    raise ValueError(f"unknown ranking kind: {kind!r}")


def _rank_by_kind(
    target_kind: str,
    tools: list[ToolCallRecord],
    date_from: str | None,
    date_to: str | None,
) -> list[RankedItem]:
    counts: dict[str, int] = {}
    errors: dict[str, int] = {}
    durations: dict[str, list[float]] = {}
    for r in tools:
        if r.kind != target_kind:
            continue
        if not _within(r.ts, date_from, date_to):
            continue
        if not r.name:
            continue
        counts[r.name] = counts.get(r.name, 0) + 1
        if r.status == "error":
            errors[r.name] = errors.get(r.name, 0) + 1
        durations.setdefault(r.name, []).append(r.duration_ms)
    items = [
        _make_ranked_item(key, counts[key], errors.get(key, 0), durations[key])
        for key in counts
    ]
    items.sort(key=lambda i: (-i.count, i.key))
    return items


def _rank_models(
    llm: list[LLMCallRecord],
    date_from: str | None,
    date_to: str | None,
) -> list[RankedItem]:
    counts: dict[str, int] = {}
    durations: dict[str, list[float]] = {}
    tokens: dict[str, list[int]] = {}
    for r in llm:
        if not _within(r.ts, date_from, date_to):
            continue
        # Key on ``provider/model`` so two providers with the same
        # model name don't collapse in the ranking.
        key = f"{r.provider or 'unknown'}/{r.model or 'unknown'}"
        counts[key] = counts.get(key, 0) + 1
        durations.setdefault(key, []).append(r.duration_ms)
        tokens.setdefault(key, []).append(r.prompt_tokens + r.completion_tokens)
    items: list[RankedItem] = []
    for key in counts:
        n = counts[key]
        sorted_d = sorted(durations[key])
        avg_tokens = sum(tokens[key]) / n if n else 0.0
        item = RankedItem(
            key=key,
            count=n,
            avg_duration_ms=sum(durations[key]) / n if n else 0.0,
            avg_tokens=avg_tokens,
        )
        if sorted_d:
            item.p50_ms = _percentile(sorted_d, 0.50)
            item.p95_ms = _percentile(sorted_d, 0.95)
            item.p99_ms = _percentile(sorted_d, 0.99)
        items.append(item)
    items.sort(key=lambda i: (-i.count, i.key))
    return items


def _make_ranked_item(
    key: str, count: int, error_count: int, durations: list[float]
) -> RankedItem:
    item = RankedItem(key=key, count=count, error_count=error_count)
    if count:
        item.error_rate = error_count / count
    if durations:
        sorted_d = sorted(durations)
        item.avg_duration_ms = sum(durations) / len(durations)
        item.p50_ms = _percentile(sorted_d, 0.50)
        item.p95_ms = _percentile(sorted_d, 0.95)
        item.p99_ms = _percentile(sorted_d, 0.99)
    return item


def paginate(items: list[RankedItem], page: int, page_size: int) -> RankingPage:
    """Slice a ranked list server-side. ``page`` is 1-based."""
    total = len(items)
    start = (page - 1) * page_size
    end = start + page_size
    return RankingPage(items=items[start:end], total=total)


# ── Trend ───────────────────────────────────────────────────────────────────


def aggregate_trend(
    llm: list[LLMCallRecord],
    tools: list[ToolCallRecord],
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    conversation_count_by_day: dict[str, int] | None = None,
) -> list[TrendPoint]:
    """One :class:`TrendPoint` per day in the requested range,
    zero-filled for empty days.

    The day range is the union of (record days ∩ window) plus
    (conversation days ∩ window), so a day with only sessions
    (no LLM calls) still shows up as a chart point.
    """
    day_llm: dict[str, list[LLMCallRecord]] = {}
    day_tools: dict[str, list[ToolCallRecord]] = {}
    for r in llm:
        if not _within(r.ts, date_from, date_to):
            continue
        day_llm.setdefault(_day(r.ts), []).append(r)
    for r in tools:
        if not _within(r.ts, date_from, date_to):
            continue
        day_tools.setdefault(_day(r.ts), []).append(r)

    days = sorted(set(day_llm) | set(day_tools))
    conv_days = (
        {d for d, _ in (conversation_count_by_day or {}).items()}
        if conversation_count_by_day
        else set()
    )
    if not days and not conv_days:
        return []

    all_days = set(days) | conv_days
    if date_from and date_to:
        start, end = date_from, date_to
    else:
        sorted_days = sorted(all_days)
        start = date_from or (sorted_days[0] if sorted_days else "")
        end = date_to or (sorted_days[-1] if sorted_days else "")
    if not start or not end or start > end:
        return []

    points: list[TrendPoint] = []
    for day in _iter_days(start, end):
        p = TrendPoint(date=day)
        dur_total = 0.0
        for r in day_llm.get(day, []):
            p.llm_calls += 1
            p.prompt_tokens += r.prompt_tokens
            p.completion_tokens += r.completion_tokens
            dur_total += r.duration_ms
        if p.llm_calls:
            p.avg_duration_ms = dur_total / p.llm_calls
        p.total_tokens = p.prompt_tokens + p.completion_tokens
        for r in day_tools.get(day, []):
            if r.kind == "skill":
                p.skill_calls += 1
            elif r.kind == "mcp":
                p.mcp_calls += 1
            else:
                p.tool_calls += 1
        if conversation_count_by_day:
            p.conversations = conversation_count_by_day.get(day, 0)
        points.append(p)
    return points


__all__ = [
    "aggregate_summary",
    "aggregate_trend",
    "paginate",
    "rank_items",
]
