"""Tests for JSONLMetricsRepository + InMemoryMetricsRepository.

These cover the storage backends' shape — record serialization,
corrupt-line tolerance, pagination surface, and Protocol
conformance. Pure aggregation semantics live in
``test_metrics_aggregations.py``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from mhc_desktop_backend.metrics.protocols import MetricsRepositoryProtocol
from mhc_desktop_backend.metrics.types import LLMCallRecord, ToolCallRecord
from mhc_desktop_deploy.impls.file_stores.metrics_store import (
    InMemoryMetricsRepository,
    JSONLMetricsRepository,
)


def _iso(yyyy: int, mm: int, dd: int, hh: int = 0) -> str:
    return (
        datetime(yyyy, mm, dd, hh, 0, 0, tzinfo=UTC).isoformat().replace("+00:00", "Z")
    )


# ── Protocol conformance ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_jsonl_repo_conforms_to_protocol(tmp_path: Path) -> None:
    repo = JSONLMetricsRepository(tmp_path / "m.jsonl")
    assert isinstance(repo, MetricsRepositoryProtocol)


@pytest.mark.asyncio
async def test_in_memory_repo_conforms_to_protocol() -> None:
    repo = InMemoryMetricsRepository()
    assert isinstance(repo, MetricsRepositoryProtocol)


# ── JSONL write ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_jsonl_appends_one_line_per_event(tmp_path: Path) -> None:
    repo = JSONLMetricsRepository(tmp_path / "m.jsonl")
    await repo.record_llm_call(
        LLMCallRecord(
            ts=_iso(2026, 8, 25),
            session_id="s",
            provider="p",
            model="m",
            prompt_tokens=1,
            completion_tokens=2,
            duration_ms=10.0,
            status="ok",
        )
    )
    await repo.record_tool_call(
        ToolCallRecord(
            ts=_iso(2026, 8, 25),
            session_id="s",
            kind="tool",
            name="read_file",
            status="ok",
        )
    )
    text = (tmp_path / "m.jsonl").read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert len(lines) == 2
    first = json.loads(lines[0])
    second = json.loads(lines[1])
    assert first["type"] == "llm"
    assert first["model"] == "m"
    assert second["type"] == "tool"
    assert second["kind"] == "tool"
    assert second["name"] == "read_file"


@pytest.mark.asyncio
async def test_jsonl_omits_empty_default_fields(tmp_path: Path) -> None:
    """Default-valued fields (error='', cancelled=False) are dropped."""
    repo = JSONLMetricsRepository(tmp_path / "m.jsonl")
    await repo.record_llm_call(
        LLMCallRecord(
            ts=_iso(2026, 8, 25),
            session_id="s",
            provider="p",
            model="m",
            prompt_tokens=1,
            completion_tokens=2,
            duration_ms=10.0,
            status="ok",
        )
    )
    line = (tmp_path / "m.jsonl").read_text("utf-8").strip()
    payload = json.loads(line)
    assert "error" not in payload
    assert "cancelled" not in payload


@pytest.mark.asyncio
async def test_jsonl_corrupt_lines_are_skipped_not_fatal(tmp_path: Path) -> None:
    repo = JSONLMetricsRepository(tmp_path / "m.jsonl")
    await repo.record_llm_call(
        LLMCallRecord(
            ts=_iso(2026, 8, 25),
            session_id="s",
            provider="p",
            model="m",
            prompt_tokens=1,
            completion_tokens=2,
            duration_ms=10.0,
            status="ok",
        )
    )
    # Inject a corrupt line, then write a valid one after.
    (tmp_path / "m.jsonl").write_text(
        "this is not json\n" + (tmp_path / "m.jsonl").read_text("utf-8"),
        encoding="utf-8",
    )
    s = await repo.query_summary()
    assert s.llm_call_count == 1


@pytest.mark.asyncio
async def test_jsonl_create_parent_dir(tmp_path: Path) -> None:
    nested = tmp_path / "deep" / "sub" / "m.jsonl"
    repo = JSONLMetricsRepository(nested)
    await repo.record_llm_call(
        LLMCallRecord(
            ts=_iso(2026, 8, 25),
            session_id="s",
            provider="p",
            model="m",
            prompt_tokens=1,
            completion_tokens=2,
            duration_ms=10.0,
            status="ok",
        )
    )
    assert nested.exists()


# ── JSONL read ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_jsonl_query_summary_with_no_file(tmp_path: Path) -> None:
    repo = JSONLMetricsRepository(tmp_path / "missing.jsonl")
    s = await repo.query_summary()
    assert s.llm_call_count == 0


@pytest.mark.asyncio
async def test_jsonl_round_trip_preserves_all_fields(tmp_path: Path) -> None:
    repo = JSONLMetricsRepository(tmp_path / "m.jsonl")
    await repo.record_llm_call(
        LLMCallRecord(
            ts=_iso(2026, 8, 25, 10),
            session_id="s1",
            provider="openai",
            model="gpt-4o-mini",
            prompt_tokens=100,
            completion_tokens=50,
            duration_ms=200.0,
            status="ok",
            error="",
            cancelled=False,
        )
    )
    s = await repo.query_summary()
    assert s.llm_call_count == 1
    assert s.prompt_tokens == 100
    assert s.completion_tokens == 50


@pytest.mark.asyncio
async def test_jsonl_ranking_rejects_unknown_kind(tmp_path: Path) -> None:
    repo = JSONLMetricsRepository(tmp_path / "m.jsonl")
    with pytest.raises(ValueError, match="unknown ranking kind"):
        await repo.query_ranking(kind="bogus")


@pytest.mark.asyncio
async def test_jsonl_pagination_slices_items(tmp_path: Path) -> None:
    repo = JSONLMetricsRepository(tmp_path / "m.jsonl")
    for i in range(15):
        await repo.record_tool_call(
            ToolCallRecord(
                ts=_iso(2026, 8, 25),
                session_id=f"s{i}",
                kind="tool",
                name=f"tool_{i}",
                status="ok",
            )
        )
    page1 = await repo.query_ranking(kind="tools", page=1, page_size=10)
    page2 = await repo.query_ranking(kind="tools", page=2, page_size=10)
    assert page1.total == 15
    assert len(page1.items) == 10
    assert len(page2.items) == 5
    seen = {it.key for it in page1.items} | {it.key for it in page2.items}
    assert len(seen) == 15


# ── InMemory repo ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_in_memory_repo_is_thread_safe_under_concurrency() -> None:
    import asyncio

    repo = InMemoryMetricsRepository()

    async def push(i: int) -> None:
        await repo.record_llm_call(
            LLMCallRecord(
                ts=_iso(2026, 8, 25),
                session_id=f"s{i}",
                provider="p",
                model="m",
                prompt_tokens=1,
                completion_tokens=1,
                duration_ms=1.0,
                status="ok",
            )
        )

    await asyncio.gather(*(push(i) for i in range(50)))
    s = await repo.query_summary()
    assert s.llm_call_count == 50
