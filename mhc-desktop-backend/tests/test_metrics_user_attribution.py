"""Unit tests for user attribution through the chat record helpers.

Covers the RFC's "user threading" requirement at the narrowest
layer: ``_record_llm`` / ``_record_tool`` must stamp ``user_id`` on
every record they write, and ``current_user_id`` must resolve the
username from ``request.state.user`` (or ``""`` when absent).
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any

import pytest

from mhc_desktop_backend.api._user_context import current_user_id
from mhc_desktop_backend.api.chat import (
    _record_llm,
    _record_tool,
)
from mhc_desktop_backend.protocols import AuthUser


class _RecordingRepo:
    def __init__(self) -> None:
        self.llm: list[Any] = []
        self.tools: list[Any] = []

    async def record_llm_call(self, record: Any) -> None:
        self.llm.append(record)

    async def record_tool_call(self, record: Any) -> None:
        self.tools.append(record)


@pytest.mark.asyncio
async def test_current_user_id_variants() -> None:
    # No user at all → "".
    assert current_user_id(SimpleNamespace(state=SimpleNamespace())) == ""
    # No state at all → "" (fails soft).
    assert current_user_id(SimpleNamespace()) == ""
    # Logged-in principal → username.
    req = SimpleNamespace(
        state=SimpleNamespace(
            user=AuthUser(id="u1", username="alice", display_name="Alice")
        )
    )
    assert current_user_id(req) == "alice"


@pytest.mark.asyncio
async def test_record_llm_stamps_user_id() -> None:
    repo = _RecordingRepo()
    await _record_llm(
        repo,
        session_id="s1",
        provider="p",
        model="m",
        started_at=time.monotonic(),
        final_response=None,
        cancelled=False,
        user_id="alice",
    )
    assert repo.llm
    assert repo.llm[0].user_id == "alice"


@pytest.mark.asyncio
async def test_record_tool_stamps_user_id_on_tool_and_skill() -> None:
    repo = _RecordingRepo()
    await _record_tool(
        repo,
        session_id="s1",
        name="load_skill",
        started_at=time.monotonic(),
        ok=True,
        args={"slug": "commit-message"},
        user_id="bob",
    )
    # tool-kind record + skill-kind record both carry user_id.
    assert len(repo.tools) == 2
    assert all(t.user_id == "bob" for t in repo.tools)
