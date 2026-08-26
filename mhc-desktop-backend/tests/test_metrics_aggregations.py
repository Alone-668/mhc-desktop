"""Tests for pure aggregation helpers (no IO).

These pin the dashboard's metric semantics independent of
storage — the same shapes flow from JSONL, SQLite, Postgres, or
in-memory backends.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

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
    RankedItem,
    ToolCallRecord,
)


def _iso(yyyy: int, mm: int, dd: int, hh: int = 0) -> str:
    return (
        datetime(yyyy, mm, dd, hh, 0, 0, tzinfo=UTC).isoformat().replace("+00:00", "Z")
    )


# ── Summary ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_summary_empty_records_returns_zeros() -> None:
    s = aggregate_summary([], [])
    assert s.llm_call_count == 0
    assert s.tool_call_count == 0
    assert s.skill_call_count == 0
    assert s.mcp_call_count == 0
    assert s.error_rate == 0.0
    assert s.avg_duration_ms == 0.0


@pytest.mark.asyncio
async def test_summary_aggregates_llm_calls_by_kind() -> None:
    llm = [
        LLMCallRecord(
            ts=_iso(2026, 8, 25, 10),
            session_id="s1",
            provider="openai",
            model="gpt-4o-mini",
            prompt_tokens=100,
            completion_tokens=50,
            duration_ms=200.0,
            status="ok",
        ),
        LLMCallRecord(
            ts=_iso(2026, 8, 25, 11),
            session_id="s2",
            provider="openai",
            model="gpt-4o-mini",
            prompt_tokens=200,
            completion_tokens=80,
            duration_ms=400.0,
            status="error",
            error="boom",
        ),
        LLMCallRecord(
            ts=_iso(2026, 8, 25, 12),
            session_id="s3",
            provider="openai",
            model="gpt-4o",
            prompt_tokens=50,
            completion_tokens=20,
            duration_ms=100.0,
            status="ok",
        ),
    ]
    tools = [
        ToolCallRecord(
            ts=_iso(2026, 8, 25, 10),
            session_id="s1",
            kind="tool",
            name="read_file",
            duration_ms=10.0,
            status="ok",
        ),
        ToolCallRecord(
            ts=_iso(2026, 8, 25, 10),
            session_id="s1",
            kind="tool",
            name="read_file",
            duration_ms=20.0,
            status="error",
        ),
        ToolCallRecord(
            ts=_iso(2026, 8, 25, 11),
            session_id="s2",
            kind="skill",
            name="commit-message",
            status="ok",
        ),
        ToolCallRecord(
            ts=_iso(2026, 8, 25, 11),
            session_id="s2",
            kind="mcp",
            name="github-mcp",
            status="ok",
        ),
    ]
    s = aggregate_summary(llm, tools)
    assert s.llm_call_count == 3
    assert s.llm_error_count == 1
    assert s.error_rate == pytest.approx(1 / 3, rel=1e-3)
    assert s.prompt_tokens == 350
    assert s.completion_tokens == 150
    assert s.total_tokens == 500
    assert s.avg_tokens_per_call == pytest.approx(500 / 3, rel=1e-3)
    assert s.tool_call_count == 2
    assert s.tool_error_count == 1
    assert s.skill_call_count == 1
    assert s.mcp_call_count == 1
    # Model perf: sorted by call_count desc → gpt-4o-mini (2) first
    assert s.model_perf[0]["model"] == "gpt-4o-mini"
    assert s.model_perf[0]["call_count"] == 2
    assert s.model_perf[0]["avg_tokens"] == pytest.approx((150 + 280) / 2, rel=1e-3)
    # p99 must be present (not the same as p95) when there are samples.
    assert "p99_ms" in s.model_perf[0]


@pytest.mark.asyncio
async def test_summary_date_range_filters_records() -> None:
    llm = [
        LLMCallRecord(
            ts=_iso(2026, 8, 20),
            session_id="s",
            provider="p",
            model="m",
            prompt_tokens=10,
            completion_tokens=5,
            duration_ms=100.0,
            status="ok",
        ),
        LLMCallRecord(
            ts=_iso(2026, 8, 25),
            session_id="s",
            provider="p",
            model="m",
            prompt_tokens=20,
            completion_tokens=10,
            duration_ms=200.0,
            status="ok",
        ),
    ]
    s = aggregate_summary(llm, [], date_from="2026-08-25", date_to="2026-08-25")
    assert s.llm_call_count == 1
    assert s.total_tokens == 30


@pytest.mark.asyncio
async def test_summary_uses_conversation_count_by_day() -> None:
    conv = {"2026-08-25": 3, "2026-08-26": 1, "2026-08-19": 99}
    s = aggregate_summary(
        [],
        [],
        date_from="2026-08-20",
        date_to="2026-08-30",
        conversation_count_by_day=conv,
    )
    assert s.conversation_count == 4  # 3 + 1; 19 is out of range


# ── Ranking ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ranking_tools_groups_by_name_with_error_rate() -> None:
    tools = [
        ToolCallRecord(
            ts=_iso(2026, 8, 25, 10),
            session_id="s",
            kind="tool",
            name="read_file",
            duration_ms=10,
            status="ok",
        ),
        ToolCallRecord(
            ts=_iso(2026, 8, 25, 10),
            session_id="s",
            kind="tool",
            name="read_file",
            duration_ms=20,
            status="error",
        ),
        ToolCallRecord(
            ts=_iso(2026, 8, 25, 10),
            session_id="s",
            kind="tool",
            name="read_file",
            duration_ms=30,
            status="ok",
        ),
        ToolCallRecord(
            ts=_iso(2026, 8, 25, 10),
            session_id="s",
            kind="tool",
            name="write_file",
            duration_ms=5,
            status="ok",
        ),
        ToolCallRecord(
            ts=_iso(2026, 8, 25, 10),
            session_id="s",
            kind="skill",
            name="commit-message",
            status="ok",
        ),
    ]
    items = rank_items(RANKING_KIND_TOOLS, [], tools)
    assert len(items) == 2
    assert items[0].key == "read_file"
    assert items[0].count == 3
    assert items[0].error_count == 1
    assert items[0].error_rate == pytest.approx(1 / 3)
    # p50/p95/p99 must be present
    assert items[0].p50_ms == 20.0  # sorted_d=[10,20,30]; nearest-rank p50 = sorted[1]
    assert items[0].p95_ms == 30.0
    assert items[0].p99_ms == 30.0
    assert items[1].key == "write_file"


@pytest.mark.asyncio
async def test_ranking_skills_filters_to_skill_kind_only() -> None:
    tools = [
        ToolCallRecord(
            ts=_iso(2026, 8, 25),
            session_id="s",
            kind="skill",
            name="commit-message",
            status="ok",
        ),
        ToolCallRecord(
            ts=_iso(2026, 8, 25),
            session_id="s",
            kind="skill",
            name="commit-message",
            status="ok",
        ),
        ToolCallRecord(
            ts=_iso(2026, 8, 25),
            session_id="s",
            kind="skill",
            name="review",
            status="ok",
        ),
        ToolCallRecord(
            ts=_iso(2026, 8, 25),
            session_id="s",
            kind="mcp",
            name="github-mcp",
            status="ok",
        ),
        ToolCallRecord(
            ts=_iso(2026, 8, 25),
            session_id="s",
            kind="tool",
            name="read_file",
            status="ok",
        ),
    ]
    items = rank_items(RANKING_KIND_SKILLS, [], tools)
    assert [i.key for i in items] == ["commit-message", "review"]
    assert items[0].count == 2


@pytest.mark.asyncio
async def test_ranking_mcps_filters_to_mcp_kind_only() -> None:
    tools = [
        ToolCallRecord(
            ts=_iso(2026, 8, 25),
            session_id="s",
            kind="mcp",
            name="github-mcp",
            status="ok",
        ),
        ToolCallRecord(
            ts=_iso(2026, 8, 25),
            session_id="s",
            kind="mcp",
            name="github-mcp",
            status="error",
            error="auth",
        ),
        ToolCallRecord(
            ts=_iso(2026, 8, 25),
            session_id="s",
            kind="mcp",
            name="github-mcp",
            status="ok",
        ),
        ToolCallRecord(
            ts=_iso(2026, 8, 25), session_id="s", kind="mcp", name="fs-mcp", status="ok"
        ),
    ]
    items = rank_items(RANKING_KIND_MCPS, [], tools)
    assert items[0].key == "github-mcp"
    assert items[0].count == 3
    assert items[0].error_count == 1
    assert items[0].error_rate == pytest.approx(1 / 3)
    assert items[1].key == "fs-mcp"


@pytest.mark.asyncio
async def test_ranking_models_keys_on_provider_model_with_p99() -> None:
    # 20 calls for openai/gpt-4o-mini with linearly increasing
    # durations — p50/p95/p99 should land on distinct samples.
    durations = [float(i + 1) * 10.0 for i in range(20)]
    llm = [
        LLMCallRecord(
            ts=_iso(2026, 8, 25, 10),
            session_id=f"s{i}",
            provider="openai",
            model="gpt-4o-mini",
            prompt_tokens=100,
            completion_tokens=50,
            duration_ms=d,
            status="ok",
        )
        for i, d in enumerate(durations)
    ]
    llm.append(
        LLMCallRecord(
            ts=_iso(2026, 8, 25, 10),
            session_id="sX",
            provider="anthropic",
            model="claude-haiku",
            prompt_tokens=200,
            completion_tokens=80,
            duration_ms=300.0,
            status="ok",
        )
    )
    items = rank_items(RANKING_KIND_MODELS, llm, [])
    assert items[0].key == "openai/gpt-4o-mini"
    assert items[0].count == 20
    # 20 samples [10,20,...,200]; nearest-rank p50 = sorted[10] = 110.
    assert items[0].p50_ms == 110.0
    assert items[0].p95_ms == 200.0  # sorted[int(20*0.95)] = sorted[19] = 200
    assert items[0].p99_ms == 200.0
    # avg_tokens = (100+50)=150 per call
    assert items[0].avg_tokens == 150.0
    assert items[1].key == "anthropic/claude-haiku"


@pytest.mark.asyncio
async def test_ranking_unknown_kind_raises() -> None:
    with pytest.raises(ValueError, match="unknown ranking kind"):
        rank_items("bogus", [], [])


# ── Pagination ─────────────────────────────────────────────────────────────


def test_pagination_slices_items_and_reports_total() -> None:
    items = [RankedItem(key=f"k{i}", count=i) for i in range(1, 25)]
    p = paginate(items, page=2, page_size=10)
    assert p.total == 24
    assert [i.key for i in p.items] == [f"k{i}" for i in range(11, 21)]


# ── Trend ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_trend_zero_fills_missing_days() -> None:
    llm = [
        LLMCallRecord(
            ts=_iso(2026, 8, 25, 10),
            session_id="s",
            provider="p",
            model="m",
            prompt_tokens=10,
            completion_tokens=5,
            duration_ms=100.0,
            status="ok",
        ),
        LLMCallRecord(
            ts=_iso(2026, 8, 27, 10),
            session_id="s",
            provider="p",
            model="m",
            prompt_tokens=20,
            completion_tokens=10,
            duration_ms=200.0,
            status="ok",
        ),
    ]
    points = aggregate_trend(llm, [], date_from="2026-08-25", date_to="2026-08-27")
    assert [p.date for p in points] == ["2026-08-25", "2026-08-26", "2026-08-27"]
    assert points[0].llm_calls == 1
    assert points[1].llm_calls == 0  # zero-filled
    assert points[1].prompt_tokens == 0
    assert points[2].llm_calls == 1


@pytest.mark.asyncio
async def test_trend_includes_conversation_only_days() -> None:
    points = aggregate_trend(
        [],
        [],
        date_from="2026-08-25",
        date_to="2026-08-25",
        conversation_count_by_day={"2026-08-25": 2},
    )
    assert len(points) == 1
    assert points[0].conversations == 2
    assert points[0].llm_calls == 0


@pytest.mark.asyncio
async def test_trend_separates_tool_skill_mcp_calls() -> None:
    tools = [
        ToolCallRecord(
            ts=_iso(2026, 8, 25),
            session_id="s",
            kind="tool",
            name="read_file",
            status="ok",
        ),
        ToolCallRecord(
            ts=_iso(2026, 8, 25),
            session_id="s",
            kind="tool",
            name="read_file",
            status="ok",
        ),
        ToolCallRecord(
            ts=_iso(2026, 8, 25),
            session_id="s",
            kind="skill",
            name="commit-message",
            status="ok",
        ),
        ToolCallRecord(
            ts=_iso(2026, 8, 25),
            session_id="s",
            kind="mcp",
            name="github-mcp",
            status="ok",
        ),
    ]
    points = aggregate_trend([], tools)
    assert points[0].tool_calls == 2
    assert points[0].skill_calls == 1
    assert points[0].mcp_calls == 1
