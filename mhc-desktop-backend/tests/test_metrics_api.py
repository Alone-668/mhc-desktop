"""End-to-end tests for the metrics dashboard API.

These cover the wire surface (HTTP shape + status codes) plus the
real interactions with the session store — conversation counts
flow into the summary and trend even when no LLM call was ever
made.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from mhc_desktop_deploy.assemble import build_default_app
from mhc_desktop_deploy.impls.file_stores.session_store import SessionStore


def _iso(yyyy: int, mm: int, dd: int) -> str:
    return (
        datetime(yyyy, mm, dd, 12, 0, 0, tzinfo=UTC).isoformat().replace("+00:00", "Z")
    )


def _inject_metrics(path: Path, events: list[dict[str, Any]]) -> None:
    """Write a JSONL metrics file directly (bypass the chat handler)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Wire a fresh app backed by tmp dirs for sessions + metrics."""
    monkeypatch.setenv("MHC_DATA_DIR_OVERRIDE", "")  # sanity
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    metrics_file = tmp_path / "metrics.jsonl"
    providers = tmp_path / "providers.json"
    providers.write_text(
        json.dumps(
            [
                {
                    "name": "stub",
                    "provider_type": "openai",
                    "api_key": "k",
                    "base_url": "",
                    "default_model": "m",
                }
            ]
        )
    )
    skills_state = tmp_path / "skills-state.json"
    skills_state.write_text("[]")
    mcp_state = tmp_path / "mcp-state.json"
    mcp_state.write_text("[]")
    tools_state = tmp_path / "tools-state.json"
    tools_state.write_text("[]")
    prefs_file = tmp_path / "prefs.json"
    prefs_file.write_text("{}")

    # Patch the path constants BEFORE create_app loads them.
    from mhc_desktop_deploy.impls.file_stores import paths

    monkeypatch.setattr(paths, "DATA_DIR", tmp_path)
    monkeypatch.setattr(paths, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(paths, "SESSIONS_INDEX", sessions_dir / "index.json")
    monkeypatch.setattr(paths, "METRICS_FILE", metrics_file)
    monkeypatch.setattr(paths, "PROVIDERS_FILE", providers)
    monkeypatch.setattr(paths, "SKILLS_STATE_FILE", skills_state)
    monkeypatch.setattr(paths, "MCP_STATE_FILE", mcp_state)
    monkeypatch.setattr(paths, "TOOLS_STATE_FILE", tools_state)
    monkeypatch.setattr(paths, "PREFS_FILE", prefs_file)

    # ``SessionStore`` (and other stores) ``from ... import SESSIONS_DIR``
    # so monkeypatching ``paths.SESSIONS_DIR`` only mutates the constant
    # in ``paths`` — each store's own module-level binding is what
    # ``__init__`` actually uses. Patch them too.
    from mhc_desktop_deploy.impls.file_stores import session_store as sstore_mod
    from mhc_desktop_deploy.impls.file_stores import provider_store as pstore_mod
    from mhc_desktop_deploy.impls.file_stores import prefs_store as pfstore_mod
    from mhc_desktop_deploy.impls.file_stores import metrics_store as mstore_mod

    monkeypatch.setattr(sstore_mod, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(pstore_mod, "PROVIDERS_FILE", providers)
    monkeypatch.setattr(pfstore_mod, "PREFS_FILE", prefs_file)
    monkeypatch.setattr(mstore_mod, "METRICS_FILE", metrics_file)

    app = build_default_app(auth=None)
    return {
        "app": app,
        "sessions_dir": sessions_dir,
        "metrics_file": metrics_file,
        "client": TestClient(app),
    }


# ── Wire shape ────────────────────────────────────────────────────────────


def test_summary_returns_zero_card_when_no_history(env) -> None:
    r = env["client"].get("/api/v1/metrics/summary")
    assert r.status_code == 200
    body = r.json()
    assert body["llm_call_count"] == 0
    assert body["tool_call_count"] == 0
    assert body["skill_call_count"] == 0
    assert body["mcp_call_count"] == 0
    assert body["conversation_count"] == 0
    assert body["total_tokens"] == 0
    assert "model_perf" in body


def test_summary_invalid_date_yields_422(env) -> None:
    r = env["client"].get("/api/v1/metrics/summary?date_from=not-a-date")
    assert r.status_code == 422


def test_summary_reversed_dates_yields_422(env) -> None:
    r = env["client"].get(
        "/api/v1/metrics/summary?date_from=2026-08-30&date_to=2026-08-20"
    )
    assert r.status_code == 422


def test_ranking_unknown_kind_yields_422(env) -> None:
    r = env["client"].get("/api/v1/metrics/ranking?kind=bogus")
    assert r.status_code == 422


def test_ranking_empty_returns_empty_items(env) -> None:
    r = env["client"].get("/api/v1/metrics/ranking?kind=tools")
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "tools"
    assert body["items"] == []
    assert body["total"] == 0


def test_trend_empty_returns_empty_points(env) -> None:
    r = env["client"].get("/api/v1/metrics/trend")
    assert r.status_code == 200
    assert r.json()["points"] == []


# ── With real events ───────────────────────────────────────────────────────


def test_summary_aggregates_llm_tool_skill_mcp(env) -> None:
    _inject_metrics(
        env["metrics_file"],
        [
            {
                "type": "llm",
                "ts": _iso(2026, 8, 25),
                "session_id": "s1",
                "provider": "openai",
                "model": "gpt-4o-mini",
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "duration_ms": 200.0,
                "status": "ok",
            },
            {
                "type": "tool",
                "ts": _iso(2026, 8, 25),
                "session_id": "s1",
                "kind": "tool",
                "name": "read_file",
                "duration_ms": 10.0,
                "status": "ok",
            },
            {
                "type": "tool",
                "ts": _iso(2026, 8, 25),
                "session_id": "s1",
                "kind": "skill",
                "name": "commit-message",
                "status": "ok",
            },
            {
                "type": "tool",
                "ts": _iso(2026, 8, 25),
                "session_id": "s1",
                "kind": "mcp",
                "name": "github-mcp",
                "status": "ok",
            },
        ],
    )
    r = env["client"].get(
        "/api/v1/metrics/summary?date_from=2026-08-25&date_to=2026-08-25"
    )
    body = r.json()
    assert body["llm_call_count"] == 1
    assert body["tool_call_count"] == 1
    assert body["skill_call_count"] == 1
    assert body["mcp_call_count"] == 1
    assert body["prompt_tokens"] == 100


def test_ranking_pagination_slices_server_side(env) -> None:
    events = [
        {
            "type": "tool",
            "ts": _iso(2026, 8, 25),
            "session_id": f"s{i}",
            "kind": "tool",
            "name": f"tool_{i:02d}",
            "status": "ok",
        }
        for i in range(15)
    ]
    _inject_metrics(env["metrics_file"], events)
    r = env["client"].get("/api/v1/metrics/ranking?kind=tools&page=2&page_size=10")
    body = r.json()
    assert body["total"] == 15
    assert len(body["items"]) == 5


def test_trend_zero_fills_missing_days(env) -> None:
    _inject_metrics(
        env["metrics_file"],
        [
            {
                "type": "llm",
                "ts": _iso(2026, 8, 25),
                "session_id": "s",
                "provider": "p",
                "model": "m",
                "prompt_tokens": 1,
                "completion_tokens": 2,
                "duration_ms": 50.0,
                "status": "ok",
            },
        ],
    )
    r = env["client"].get(
        "/api/v1/metrics/trend?date_from=2026-08-25&date_to=2026-08-27"
    )
    points = r.json()["points"]
    assert [p["date"] for p in points] == [
        "2026-08-25",
        "2026-08-26",
        "2026-08-27",
    ]
    assert points[1]["llm_calls"] == 0  # zero-filled


def test_summary_includes_conversation_count_from_session_store(env) -> None:
    """The summary's conversation_count field is sourced from
    ``count_by_day`` on the session store — verified by creating two
    sessions on the same day and reading the API."""
    # Inject two sessions through the real SessionStore.
    sessions_dir = env["sessions_dir"]
    sessions_dir.mkdir(parents=True, exist_ok=True)
    (sessions_dir / "index.json").write_text(
        json.dumps(
            [
                {
                    "id": "s1",
                    "title": "one",
                    "provider": "",
                    "model": "",
                    "created_at": _iso(2026, 8, 25),
                    "updated_at": _iso(2026, 8, 25),
                },
                {
                    "id": "s2",
                    "title": "two",
                    "provider": "",
                    "model": "",
                    "created_at": _iso(2026, 8, 25),
                    "updated_at": _iso(2026, 8, 25),
                },
            ]
        )
    )
    r = env["client"].get(
        "/api/v1/metrics/summary?date_from=2026-08-25&date_to=2026-08-25"
    )
    body = r.json()
    assert body["conversation_count"] == 2


def test_session_store_count_by_day_filters_out_of_range(tmp_path: Path) -> None:
    """SessionStore.count_by_day must respect date_from / date_to."""
    import asyncio

    from mhc_desktop_deploy.impls.file_stores import session_store as sstore_mod

    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    (sessions_dir / "index.json").write_text(
        json.dumps(
            [
                {
                    "id": "s1",
                    "title": "old",
                    "provider": "",
                    "model": "",
                    "created_at": _iso(2026, 8, 1),
                    "updated_at": _iso(2026, 8, 1),
                },
                {
                    "id": "s2",
                    "title": "in",
                    "provider": "",
                    "model": "",
                    "created_at": _iso(2026, 8, 25),
                    "updated_at": _iso(2026, 8, 25),
                },
            ]
        )
    )
    original_dir = sstore_mod.SESSIONS_DIR
    sstore_mod.SESSIONS_DIR = sessions_dir
    try:
        fresh = SessionStore()  # picks up the patched module constant
        counts = asyncio.run(fresh.count_by_day("2026-08-20", "2026-08-30"))
        assert counts == {"2026-08-25": 1}
    finally:
        sstore_mod.SESSIONS_DIR = original_dir
