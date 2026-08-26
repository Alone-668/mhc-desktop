"""Tests for chat-session integration: per-session event tagging,
the in-process stream registry, the cancel endpoint, and the
graceful-shutdown lifespan handler.

These tests do not require a live LLM provider. They exercise the
parts of the chat router that touch ``session_id`` and the registry
via in-process ASGI calls.
"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from mhc_desktop_backend.api.chat import router as chat_router
from mhc_desktop_backend.api.providers import router as providers_router
from mhc_desktop_deploy.impls.file_stores.stream_registry import StreamRegistry


@pytest.fixture
def app_with_registry(monkeypatch):
    """FastAPI app wired with just the providers + chat routers and a
    fresh StreamRegistry. We give the chat router a minimal
    ProviderStore stub that returns ``None`` for ``get`` so the chat
    loop fails fast — these tests don't care about the LLM, only about
    the registry + event tagging.
    """

    class _StubProviderStore:
        async def get(self, _name):
            return None

    app = FastAPI()
    app.state.provider_store = _StubProviderStore()
    app.state.session_store = None
    app.state.skill_store = None
    app.state.mcp_store = None
    app.state.mcp_manager = None
    app.state.stream_registry = StreamRegistry()
    app.include_router(chat_router)
    app.include_router(providers_router)
    return app


@pytest.mark.asyncio
async def test_chat_emits_session_id_and_seq_on_every_event(app_with_registry):
    """Every event payload MUST carry ``session_id`` and a monotonic
    ``seq`` so the frontend can route events into the right
    consumer without race conditions."""
    app = app_with_registry
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.post(
            "/api/v1/chat",
            json={
                "provider": "openai",
                "model": "gpt-4o-mini",
                "session_id": "sess-abc",
                "assistant_message_id": "msg-1",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        assert r.status_code == 200
        body = r.text
        assert "event: error" in body, body
        # Pull the first data line for the error event and assert it
        # carries session_id + seq.
        lines = [line for line in body.splitlines() if line.startswith("data: ")]
        assert lines, body
        first = json.loads(lines[0].lstrip("data: "))
        assert first["session_id"] == "sess-abc"
        assert isinstance(first["seq"], int) and first["seq"] >= 1


@pytest.mark.asyncio
async def test_registry_replaces_previous_stream_for_same_session():
    """If a session somehow opens a second stream, the registry must
    cancel the first so we don't double-write / double-charge the LLM."""
    reg = StreamRegistry()
    s1 = await reg.register("sess-x")
    assert reg.get("sess-x") is s1
    s2 = await reg.register("sess-x")
    assert reg.get("sess-x") is s2
    # s1 should now have its cancel flag set (a previous run was
    # kicked off; the new one replaced it).
    assert s1.cancel.is_set() is True
    assert s2.cancel.is_set() is False
    await reg.unregister("sess-x")


@pytest.mark.asyncio
async def test_cancel_endpoint_signals_running_stream():
    """POST /api/v1/chat/cancel/{session_id} must trip the cancel flag
    on the registered stream so the chunk loop emits ``cancelled``."""
    app = FastAPI()
    app.state.provider_store = None
    app.state.session_store = None
    app.state.skill_store = None
    app.state.mcp_store = None
    app.state.mcp_manager = None
    app.state.stream_registry = StreamRegistry()
    app.include_router(chat_router)

    reg: StreamRegistry = app.state.stream_registry
    stream = await reg.register("sess-y")
    assert stream.cancel.is_set() is False

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.post("/api/v1/chat/cancel/sess-y")
        assert r.status_code == 204
    assert stream.cancel.is_set() is True
    assert stream.cancelled is True


@pytest.mark.asyncio
async def test_cancel_endpoint_is_noop_when_no_stream():
    """Calling cancel on a session with no running stream must return
    204 without raising — clients call this defensively on shutdown."""
    app = FastAPI()
    app.state.stream_registry = StreamRegistry()
    app.include_router(chat_router)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.post("/api/v1/chat/cancel/no-such")
        assert r.status_code == 204


@pytest.mark.asyncio
async def test_registry_cancel_all_signals_every_stream():
    """Used by the lifespan hook — must trip every stream's cancel
    flag, regardless of how many are running."""
    reg = StreamRegistry()
    a = await reg.register("a")
    b = await reg.register("b")
    c = await reg.register("c")
    await reg.cancel_all(timeout=0.1)
    assert a.cancel.is_set()
    assert b.cancel.is_set()
    assert c.cancel.is_set()


@pytest.mark.asyncio
async def test_registry_unregister_removes_entry():
    reg = StreamRegistry()
    await reg.register("z")
    assert reg.get("z") is not None
    await reg.unregister("z")
    assert reg.get("z") is None
    assert reg.active() == []


@pytest.mark.asyncio
async def test_anonymous_stream_does_not_register():
    """A request without ``session_id`` must NOT register a stream —
    the registry only holds streams the client explicitly owns."""

    class _StubProviderStore:
        async def get(self, _name):
            return None

    app = FastAPI()
    app.state.provider_store = _StubProviderStore()
    app.state.session_store = None
    app.state.skill_store = None
    app.state.mcp_store = None
    app.state.mcp_manager = None
    app.state.stream_registry = StreamRegistry()
    app.include_router(chat_router)

    reg: StreamRegistry = app.state.stream_registry
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.post(
            "/api/v1/chat",
            json={
                "provider": "openai",
                "messages": [{"role": "user", "content": "hi"}],
                # no session_id
            },
        )
        assert r.status_code == 200
    assert reg.active() == []
