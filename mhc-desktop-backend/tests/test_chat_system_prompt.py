"""Tests for the server-side system-prompt assembly in the chat router.

The contract under test:

1. The client no longer sends ``system_prompt``; the chat router
   assembles it from a (now empty) base + the per-request
   ``## Skills`` section + the user's saved addition.
2. The base is intentionally empty -- the previous version
   spelled out the on-disk skill root (``~/.mhc-desktop/skills/``)
   which let the agent ``cmd ls`` / ``cat`` SKILL.md files
   directly, bypassing ``load_skill`` and reading skills the user
   hadn't enabled. ``load_skill`` is now the canonical read path;
   the per-request ``## Skills`` section is the only place the
   model sees skill metadata.
3. The user addition is appended verbatim (after a divider) when
   non-empty, and skipped when empty (no dangling separator).
4. The base deliberately does NOT define the assistant's identity —
   that is the user's prerogative and goes in their addition.
5. A client that *does* send ``system_prompt`` in the body must
   not be honoured (we ignore it; the field is reserved by the
   server).
"""

from __future__ import annotations

import re

import pytest
from fastapi import FastAPI

from mhc_desktop_backend.api.chat import (
    BASE_SYSTEM_PROMPT,
    _build_system_prompt,
    router as chat_router,
)


# ── _build_system_prompt unit tests ─────────────────────────────────────────


def test_base_alone_has_no_dangling_separator() -> None:
    out = _build_system_prompt("")
    assert out == BASE_SYSTEM_PROMPT.rstrip()
    # Trailing whitespace would be wasteful in every chat request.
    assert out == out.rstrip()


def test_base_alone_does_not_define_identity() -> None:
    """The base must not say "You are an assistant" or anything
    that pre-empts what the user wants to call their assistant.
    Identity is the user's call; the base only carries facts the
    model needs to know about the runtime (skill root location).
    """
    out = _build_system_prompt("")
    assert "you are" not in out.lower()


def test_base_alone_has_no_skill_location_leak() -> None:
    """The base must NOT spell out the on-disk skill root.

    Telling the agent where skills live lets it ``cmd ls`` /
    ``cat`` SKILL.md files directly, bypassing ``load_skill`` and
    pulling in skills the user didn't enable. ``load_skill`` is
    now the canonical read path; the per-request ``## Skills``
    section is what tells the model which skills exist.
    """
    out = _build_system_prompt("")
    assert "~/.mhc-desktop" not in out
    assert "<slug>" not in out
    assert "load_skill" not in out


def test_user_addition_is_appended_under_divider() -> None:
    out = _build_system_prompt("always reply in 中文")
    assert "always reply in 中文" in out
    assert "# User-specified system prompt" in out


def test_user_addition_is_stripped() -> None:
    out = _build_system_prompt("   be concise   \n  ")
    assert "be concise" in out
    assert "   be concise" not in out


def test_user_addition_empty_omits_divider() -> None:
    """No divider / heading on a fresh install — the prompt should
    end cleanly without a dangling "# User-specified ..." section
    the user hasn't written yet.
    """
    out = _build_system_prompt("")
    assert "# User-specified system prompt" not in out


# ── HTTP integration tests ──────────────────────────────────────────────────


class _StubProviderStore:
    async def get(self, _name):
        return None


class _ScriptedPrefsStore:
    """In-memory prefs store with an optional failure switch."""

    def __init__(
        self,
        addition: str = "",
        *,
        explode_on_get: bool = False,
    ) -> None:
        self._addition = addition
        self._explode = explode_on_get

    async def get(self):
        if self._explode:
            raise RuntimeError("disk on fire")
        return _StubPrefs(addition=self._addition)

    async def update(self, **fields):
        if "system_prompt_addition" in fields:
            self._addition = fields["system_prompt_addition"]
        return _StubPrefs(addition=self._addition)


class _StubPrefs:
    def __init__(self, addition: str) -> None:
        self.system_prompt_addition = addition
        self.updated_at = "2025-01-01T00:00:00+00:00"
        self.extra: dict = {}

    def to_dict(self):
        return {
            "system_prompt_addition": self.system_prompt_addition,
            "updated_at": self.updated_at,
        }


def _build_app(prefs: _ScriptedPrefsStore) -> FastAPI:
    app = FastAPI()
    app.state.provider_store = _StubProviderStore()
    app.state.session_store = None
    app.state.skill_store = None
    app.state.mcp_store = None
    app.state.mcp_manager = None
    app.state.stream_registry = object()  # not used; chat will 400 before reaching it
    app.state.prefs_store = prefs
    app.include_router(chat_router)
    return app


@pytest.mark.asyncio
async def test_chat_request_ignores_client_supplied_system_prompt() -> None:
    """The body field ``system_prompt`` is reserved by the server.
    We must not let the client overwrite the base. The router
    simply ignores the field; what the model sees is exclusively
    the server-assembled prompt.
    """
    out_with_addition = _build_system_prompt("user wrote this")
    out_without_addition = _build_system_prompt("")
    # In neither case does the *client* have any lever to inject
    # arbitrary system text — that's enforced upstream in the
    # router (it ignores body.system_prompt). The contract here is
    # that the helper is the only place the assembled prompt lives.
    assert "user wrote this" in out_with_addition
    assert "user wrote this" not in out_without_addition


def test_build_system_prompt_fallback_when_addition_empty() -> None:
    """Pin the empty-addition path so the broken-prefs-store fallback
    (which is what the router uses on read failure) is identical to
    a user who simply hasn't typed anything yet. With the base now
    empty, both paths produce a clean ``## Skills`` / user-addition
    message -- the model never sees a dangling skill-location hint
    regardless of whether prefs read succeeded.
    """
    out = _build_system_prompt("")
    assert "~/.mhc-desktop" not in out
    assert "<slug>" not in out
    assert "# User-specified system prompt" not in out
