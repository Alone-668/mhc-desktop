# -*- coding: utf-8 -*-
"""Tests for the auto-title endpoint on the sessions router.

Covers:
* the endpoint only touches sessions whose title is still the
  default ``"New chat"`` placeholder (never overwrite a renamed
  title)
* the LLM path returns a cleaned Chinese title (≤10 chars, no
  punctuation / quotes leaked from the prompt)
* the LLM-failure path falls back to a hard-truncated user message
  so the sidebar still shows something readable
* the helper that strips quotes and enforces the 10-char ceiling
* missing provider / empty user_message produce the right HTTP
  error code
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from mhc_desktop_backend.api.sessions import (
    _clean_title,
    _fallback_title,
    router as sessions_router,
)


class _StubSession:
    """A session record the auto-title endpoint can read via attribute
    access (matches the real ``Session`` dataclass shape: ``.title``,
    ``.messages``)."""

    def __init__(self, sid: str, **fields: Any) -> None:
        self.id = sid
        for k, v in fields.items():
            setattr(self, k, v)

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


class _StubSessionStore:
    """Bare-bones in-memory session store for these tests.

    Only the methods the auto-title endpoint touches are
    implemented; everything else raises ``NotImplementedError``
    so we notice if the endpoint silently grows new dependencies.
    """

    def __init__(self) -> None:
        self._items: dict[str, _StubSession] = {}

    async def get(self, sid: str) -> _StubSession | None:
        return self._items.get(sid)

    async def update(self, sid: str, data: dict[str, Any]) -> _StubSession:
        existing = self._items[sid]
        for k, v in data.items():
            setattr(existing, k, v)
        return existing

    # Convenience for tests — create a session directly.
    def seed(self, sid: str, **fields: Any) -> None:
        self._items[sid] = _StubSession(sid, **fields)


class _StubProviderStore:
    """Resolves provider names to canned provider objects.

    ``register(name, title_or_none, *, fail=False)`` lets each test
    control what the LLM will return. ``fail=True`` makes the
    provider's ``build_provider`` raise so the endpoint takes the
    fallback path.
    """

    def __init__(self) -> None:
        self._items: dict[str, dict[str, Any]] = {}

    def register(
        self,
        name: str,
        returned_title: str | None,
        *,
        fail: bool = False,
    ) -> None:
        self._items[name] = {"title": returned_title, "fail": fail}

    async def get(self, name: str) -> dict[str, Any] | None:
        return self._items.get(name)


@pytest.fixture
def app(monkeypatch):
    sessions = _StubSessionStore()
    providers = _StubProviderStore()

    # The endpoint calls ``build_provider(...)`` which constructs a
    # real LLM client — too heavy for a unit test. We monkeypatch the
    # sessions router's module-level ``build_provider`` reference so
    # the test fully controls what comes back.
    import mhc_desktop_backend.api.sessions as sessions_mod

    monkeypatch.setattr(sessions_mod, "build_provider", _fake_build_provider)

    app = FastAPI()
    app.state.session_store = sessions
    app.state.provider_store = providers
    app.include_router(sessions_router)
    return app, sessions, providers


def _fake_build_provider(provider_record, **_kwargs):
    """Drop-in replacement that returns an object shaped like the
    real ``LLMProvider`` enough to drive ``llm.chat``.

    Mirrors ``minimal_harness.llm.llm.Stream``'s shape: an async
    iterator that yields deltas, then raises ``StopAsyncIteration``,
    after which ``.response`` returns the final ``LLMResponse``.
    """

    class _StubLLM:
        def __init__(self, title: str | None, fail: bool) -> None:
            self._title = title
            self._fail = fail

        async def chat(self, messages, tools, **_):
            if self._fail:
                raise RuntimeError("simulated LLM outage")

            class _Resp:
                content = self._title
                reasoning_content = None
                tool_calls: list = []
                finish_reason = "stop"
                usage = None

            # The real Stream yields deltas, then yields a final
            # LLMResponse which ``Stream.__anext__`` captures and
            # turns into ``StopAsyncIteration``. We mirror that
            # two-phase protocol.
            async def _iter():
                # Pretend a single text delta lands, then the
                # response object arrives as the terminal value.
                yield {"delta": ""}  # noqa: F841 — type-narrowing aid
                yield _Resp()

            class _Stream:
                def __init__(self, agen):
                    self._agen = agen
                    self._resp = _Resp()

                def __aiter__(self):
                    return self

                async def __anext__(self):
                    item = await self._agen.__anext__()
                    if isinstance(item, _Resp):
                        self._resp = item
                        raise StopAsyncIteration
                    return item

                @property
                def response(self):
                    return self._resp

            return _Stream(_iter())

    return _StubLLM(provider_record["title"], provider_record["fail"])


@pytest.mark.asyncio
async def test_auto_title_generates_clean_chinese_title_from_llm(app):
    _, sessions, providers = app
    sid = "sess-llm"
    sessions.seed(sid, title="New chat", messages=[])
    providers.register("my-prov", "总结一下本周的工作")

    async with AsyncClient(
        transport=ASGITransport(app=app[0]), base_url="http://t"
    ) as c:
        r = await c.post(
            f"/api/v1/sessions/{sid}/auto-title",
            json={
                "user_message": "帮我把本周的工作总结一下",
                "provider": "my-prov",
                "model": "claude-3-5-sonnet",
            },
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {"title": "总结一下本周的工作", "source": "llm"}
    assert len(body["title"]) <= 10


@pytest.mark.asyncio
async def test_auto_title_strips_quotes_and_punctuation(app):
    _, sessions, providers = app
    sid = "sess-quotes"
    sessions.seed(sid, title="New chat")
    # Model tends to wrap the title in quotes / append a colon
    providers.register("my-prov", '"总结一下本周: ""')

    async with AsyncClient(
        transport=ASGITransport(app=app[0]), base_url="http://t"
    ) as c:
        r = await c.post(
            f"/api/v1/sessions/{sid}/auto-title",
            json={"user_message": "本周工作总结", "provider": "my-prov", "model": ""},
        )
    body = r.json()
    assert body["source"] == "llm"
    assert body["title"] == "总结一下本周"
    # No leftover punctuation or quotes
    assert '"' not in body["title"]
    assert ":" not in body["title"]
    assert "。" not in body["title"]


@pytest.mark.asyncio
async def test_auto_title_truncates_to_10_chars(app):
    _, sessions, providers = app
    sid = "sess-long"
    sessions.seed(sid, title="New chat")
    providers.register("my-prov", "这是一段超过十个字的标题需要被截断")

    async with AsyncClient(
        transport=ASGITransport(app=app[0]), base_url="http://t"
    ) as c:
        r = await c.post(
            f"/api/v1/sessions/{sid}/auto-title",
            json={"user_message": "x" * 200, "provider": "my-prov", "model": ""},
        )
    body = r.json()
    assert len(body["title"]) <= 10
    # The model returned the leading 10 characters
    assert body["title"] == "这是一段超过十个字的标题需要被截断"[:10]


@pytest.mark.asyncio
async def test_auto_title_drops_trailing_think_block(app):
    _, sessions, providers = app
    sid = "sess-think"
    sessions.seed(sid, title="New chat")
    providers.register("my-prov", "思考中…</think>帮我总结一下")

    async with AsyncClient(
        transport=ASGITransport(app=app[0]), base_url="http://t"
    ) as c:
        r = await c.post(
            f"/api/v1/sessions/{sid}/auto-title",
            json={"user_message": "总结", "provider": "my-prov", "model": ""},
        )
    body = r.json()
    assert body["title"] == "帮我总结一下"


@pytest.mark.asyncio
async def test_auto_title_returns_kept_when_user_renamed(app):
    _, sessions, providers = app
    sid = "sess-renamed"
    sessions.seed(sid, title="我的项目笔记")
    providers.register("my-prov", "无关标题")

    async with AsyncClient(
        transport=ASGITransport(app=app[0]), base_url="http://t"
    ) as c:
        r = await c.post(
            f"/api/v1/sessions/{sid}/auto-title",
            json={"user_message": "anything", "provider": "my-prov", "model": ""},
        )
    body = r.json()
    assert body == {"title": "我的项目笔记", "source": "kept"}
    # Underlying session title untouched
    persisted = await sessions.get(sid)
    assert persisted.title == "我的项目笔记"


@pytest.mark.asyncio
async def test_auto_title_falls_back_when_llm_fails(app):
    _, sessions, providers = app
    sid = "sess-fail"
    sessions.seed(sid, title="New chat")
    providers.register("my-prov", None, fail=True)

    async with AsyncClient(
        transport=ASGITransport(app=app[0]), base_url="http://t"
    ) as c:
        r = await c.post(
            f"/api/v1/sessions/{sid}/auto-title",
            json={
                "user_message": "帮我看看这段日志有没有问题",
                "provider": "my-prov",
                "model": "",
            },
        )
    body = r.json()
    assert body["source"] == "fallback"
    # Fallback truncates the user message to 10 chars
    assert body["title"] == "帮我看看这段日志有没有问题"[:10]
    persisted = await sessions.get(sid)
    assert persisted.title == body["title"]


@pytest.mark.asyncio
async def test_auto_title_falls_back_when_provider_missing(app):
    _, sessions, providers = app
    sid = "sess-no-prov"
    sessions.seed(sid, title="New chat")
    # No provider registered for "missing-prov"

    async with AsyncClient(
        transport=ASGITransport(app=app[0]), base_url="http://t"
    ) as c:
        r = await c.post(
            f"/api/v1/sessions/{sid}/auto-title",
            json={
                "user_message": "中文标题 fallback 测试",
                "provider": "missing-prov",
                "model": "",
            },
        )
    body = r.json()
    assert body["source"] == "fallback"
    assert body["title"] == "中文标题 fallback 测试"[:10]


@pytest.mark.asyncio
async def test_auto_title_rejects_empty_user_message(app):
    _, sessions, _ = app
    sid = "sess-empty"
    sessions.seed(sid, title="New chat")

    async with AsyncClient(
        transport=ASGITransport(app=app[0]), base_url="http://t"
    ) as c:
        r = await c.post(
            f"/api/v1/sessions/{sid}/auto-title",
            json={"user_message": "   ", "provider": "p", "model": ""},
        )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_auto_title_404_on_unknown_session(app):
    _, _, _ = app
    async with AsyncClient(
        transport=ASGITransport(app=app[0]), base_url="http://t"
    ) as c:
        r = await c.post(
            "/api/v1/sessions/missing/auto-title",
            json={"user_message": "x", "provider": "p", "model": ""},
        )
    assert r.status_code == 404


def test_clean_title_strips_quotes():
    assert _clean_title('"hello"') == "hello"
    assert _clean_title("中文：标题") == "中文标题"
    assert _clean_title("  title  ") == "title"
    assert _clean_title("") is None
    # Punctuation stripped AND the result is truncated to 10 chars
    # (per the 10-char ceiling — a "..." stripping would otherwise
    # leave 16 chars and we'd keep going). The function is the
    # single source of truth for the cap, so we assert it here.
    assert _clean_title("only punctuation...") == "only punct"


def test_fallback_title_truncates_to_10_chars():
    assert _fallback_title("123456789012345") == "1234567890"
    assert _fallback_title("\n\n  multi  \n   line  \n  text  ") == "multi line"
    assert _fallback_title("") == "New chat"
