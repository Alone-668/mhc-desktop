"""Storage / runtime Protocols for ``mhc-desktop-backend``.

These Protocols are the contract enterprise adapters implement against.
The default file-backed implementations in :mod:`mhc_desktop_backend.storage`,
:mod:`mhc_desktop_backend.skills.store`, :mod:`mhc_desktop_backend.mcp.store`,
and :mod:`mhc_desktop_backend.tools.store` are concrete reference impls —
they don't inherit from anything here. Structural typing means any class
that exposes the same async surface passes ``isinstance(x, Protocol)``
at runtime, no inheritance required.

Why structural typing
--------------------

Customers swap the file-backed stores for Postgres / Vault / OSS-backed
ones without touching the backend's router code. The routers are typed
against these Protocols (see ``api/*.py::get_*`` helpers), so the type
checker and the runtime registry both accept any conforming object.
A customer just builds a class with the same methods and passes it to
:meth:`mhc_desktop_backend.app.create_app`'s new injection kwargs.

Why ``runtime_checkable``
-------------------------

Three reasons to keep the ``@runtime_checkable`` decoration:

1. FastAPI's dependency-injection helpers ``get_*`` can add an
   ``assert isinstance(store, ProviderStoreProtocol)`` at the top of a
   route handler — failing fast in tests beats a confusing 500.
2. Health-check handlers can probe ``isinstance(x, XProtocol)`` to
   confirm the wired adapter actually conforms (catches accidentally
   passing ``None``).
3. External monitoring / test harnesses get the same answer without
   importing the concrete classes.

What's intentionally NOT here
------------------------------

* The LLM ``Provider`` is a value object (dataclass), not an adapter —
  it's serialised JSON, not a behaviour to override. Same for ``Skill``,
``  ``MCPServer``, ``Tool``. The Protocols cover the stores and the
  MCPManager (the things with side effects and replaceable backends).
* Chat pipeline hooks (event filtering, custom SSE post-processing) are
  not abstracted yet. The user's stated requirement is "enterprise
  adaptation"; LLM-call sites already vary per provider. Add
  ``ChatHook`` Protocols when a real customer needs them — YAGNI for
  now.

Usage
-----

::

    # Concrete reference impls (the default):
    create_app()

    # Inject custom adapters — anywhere a Protocol is accepted, a
    # matching custom class works:
    create_app(
        sessions=PostgresSessionStore(dsn=...),
        providers=VaultProviderStore(url=...),
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    import asyncio

# Re-export the value objects so adapters don't need a second import
# path. These are dataclasses / TypedDicts — not Protocols.
from mhc_desktop_backend.metrics.protocols import MetricsRepositoryProtocol
from mhc_desktop_backend.protocol_models import Provider, Session
from mhc_desktop_backend.skills.models import Skill
from mhc_desktop_backend.tools.models import Tool
from mhc_desktop_backend.mcp.models import MCPServer


@dataclass(frozen=True)
class AuthUser:
    """A verified principal returned by :class:`AuthProviderProtocol`.

    The kernel hands this object to the request state (see
    :mod:`mhc_desktop_backend.auth.middleware`) so route handlers can
    read ``request.state.user``. The ``id`` is the audit key; the
    ``display_name`` and ``avatar_url`` are what the SPA's left-nav
    user card renders.

    ``upstream_credentials`` is an optional opaque dict the auth
    provider can fill in at login time so a downstream adapter
    (e.g. a :class:`MarketplaceProviderProtocol`) can forward the
    user's identity to a third-party service (the enterprise skill
    marketplace, an IdP API, ...). The kernel never inspects the
    contents; it's a typed envelope the deploy's adapters read when
    they need it.

    The mock provider leaves it ``None`` because there is no
    upstream to talk to; real IdP adapters populate it from their
    IdP's per-user token / cookie / OAuth grant.
    """

    id: str
    username: str
    display_name: str
    avatar_url: str | None = None
    upstream_credentials: dict[str, str] | None = None
    # Scopes the principal holds (e.g. ``"metrics:read"``,
    # ``"admin"``, ``"providers:write"``). The kernel auth middleware
    # consults the deploy-provided :func:`scope_required_for` callable
    # to gate routes by scope; the deploy package decides the actual
    # vocabulary so the kernel never bakes in a permission model.
    # Empty frozenset means "no scopes granted" — the middleware will
    # reject any scope-protected route for this user.
    scopes: frozenset[str] = frozenset()


# ── Session storage ──────────────────────────────────────────────────────────


@runtime_checkable
class SessionStoreProtocol(Protocol):
    """Per-session message log persistence.

    Sessions are keyed by ``sid`` (UUID string). The store owns the
    lifecycle: create / read / update / delete, plus bulk operations
    used by the management UI.
    """

    async def list(self) -> list[Session]: ...
    async def get(self, sid: str) -> Session | None: ...
    async def create(self, data: dict[str, Any] | None = None) -> Session: ...
    async def update(self, sid: str, data: dict[str, Any]) -> Session: ...
    async def delete(self, sid: str) -> None: ...
    async def delete_many(self, sids: list[str]) -> int: ...
    async def clear_all(self) -> int: ...
    async def count_by_day(
        self,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict[str, int]: ...
    async def close(self) -> None: ...


# ── Provider / LLM config storage ────────────────────────────────────────────


@runtime_checkable
class ProviderStoreProtocol(Protocol):
    """LLM provider configuration registry.

    ``list()`` returns the full set of enabled and disabled entries;
    the management UI filters. ``create`` raises ``ValueError`` on a
    duplicate name; ``update`` raises on a missing name.
    """

    async def list(self) -> list[Provider]: ...
    async def get(self, name: str) -> Provider | None: ...
    async def create(self, data: dict[str, Any]) -> Provider: ...
    async def update(self, name: str, data: dict[str, Any]) -> Provider: ...
    async def delete(self, name: str) -> None: ...
    async def close(self) -> None: ...


# ── Skills ───────────────────────────────────────────────────────────────────


@runtime_checkable
class SkillStoreProtocol(Protocol):
    """Skill folder + state persistence.

    State (``enabled``, custom description, ``origin``, ``source_path``)
    lives separately from the skill folder so re-importing doesn't
    clobber user preferences. Methods used only by the API are still
    part of the surface — adapters that omit them (e.g. read-only
    skill sources) should raise ``NotImplementedError`` rather than
    silently failing.
    """

    async def list(self) -> list[Skill]: ...
    async def get(self, slug: str) -> Skill | None: ...
    async def get_body(self, slug: str) -> str | None: ...
    async def get_file(self, slug: str, rel_path: str) -> tuple[str, bytes]: ...
    async def install_from_folder(
        self,
        source: Path,
        *,
        overwrite: bool = False,
        origin: str = "imported",
    ) -> Skill: ...
    async def delete(self, slug: str) -> None: ...
    async def set_enabled(self, slug: str, enabled: bool) -> Skill: ...
    async def update_meta(
        self,
        slug: str,
        *,
        description: str | None = None,
        body: str | None = None,
    ) -> Skill: ...
    async def export(self, slug: str) -> bytes: ...
    async def import_zip(self, data: bytes, *, origin: str = "imported") -> Skill: ...
    async def close(self) -> None: ...


# ── MCP ──────────────────────────────────────────────────────────────────────


@runtime_checkable
class MCPStoreProtocol(Protocol):
    """MCP server registry + tool catalog persistence.

    ``upsert`` is the one entry point that covers both create and
    update — it picks the right path based on whether the slug
    already exists.
    """

    async def list(self) -> list[MCPServer]: ...
    async def get(self, slug: str) -> MCPServer | None: ...
    async def upsert(
        self,
        *,
        slug: str,
        name: str,
        description: str,
        command: str,
        args: list[str],
        env: dict[str, str] | None = None,
        origin: str = "imported",
    ) -> MCPServer: ...
    async def delete(self, slug: str) -> None: ...
    async def set_enabled(self, slug: str, enabled: bool) -> MCPServer: ...
    async def record_discovery(
        self, slug: str, tools: list[dict[str, Any]], *, error: str = ""
    ) -> None: ...
    async def close(self) -> None: ...


@runtime_checkable
class MCPManagerProtocol(Protocol):
    """MCP subprocess lifecycle + JSON-RPC client.

    ``connect`` returns a handle the chat handler can call ``list_tools``
    on; ``call_tool`` is invoked from the streaming chat loop. The
    ``shutdown`` method is called from the FastAPI lifespan handler
    so background MCP subprocesses don't outlive the API process.
    """

    async def connect(self, server: MCPServer) -> Any: ...
    async def list_tools(self, server: MCPServer) -> list[dict[str, Any]]: ...
    async def call_tool(
        self,
        server: MCPServer,
        name: str,
        arguments: dict[str, Any],
    ) -> Any: ...
    async def disconnect(self, slug: str) -> None: ...
    async def shutdown(self) -> None: ...


# ── Tools ────────────────────────────────────────────────────────────────────


@runtime_checkable
class ToolStoreProtocol(Protocol):
    """Local / imported / remote Tool catalog.

    ``get_callable`` returns the Python async generator the chat
    handler streams through for ``local`` / ``bundled`` tools. For
    ``script`` / ``remote`` kinds the chat handler uses a different
    execution path, but the method must still exist (returning
    ``None`` is the convention for "not a local callable").
    """

    async def list(self) -> list[Tool]: ...
    async def get(self, slug: str) -> Tool | None: ...
    async def get_by_model_name(self, model_name: str) -> Tool | None: ...
    async def get_callable(self, slug: str) -> Any: ...
    async def create(self, data: dict[str, Any]) -> Tool: ...
    async def update(self, slug: str, data: dict[str, Any]) -> Tool: ...
    async def delete(self, slug: str) -> None: ...
    async def set_enabled(self, slug: str, enabled: bool) -> Tool: ...
    async def close(self) -> None: ...


# ── Stream registry ──────────────────────────────────────────────────────────


@runtime_checkable
class StreamRegistryProtocol(Protocol):
    """Per-session cancel-token bookkeeping.

    The chat router calls :meth:`register` once at the start of an
    SSE stream and :meth:`unregister` when the stream finishes
    (cancelled or natural). The FastAPI lifespan handler calls
    :meth:`cancel_all` at shutdown so the process can exit without
    waiting on stuck LLM providers.
    """

    async def register(self, session_id: str) -> Any: ...
    async def unregister(self, session_id: str) -> None: ...
    def get(self, session_id: str) -> Any: ...
    def active(self) -> list[str]: ...
    async def cancel_all(self, timeout: float = 3.0) -> None: ...


# ── Global user preferences ──────────────────────────────────────────────────


@runtime_checkable
class PrefsStoreProtocol(Protocol):
    """User-scoped preferences shared across all chat sessions.

    Holds the user's own additions to the system prompt and any other
    cross-session UI/runtime preferences that follow. Backed by a
    single JSON file in the user's data dir; the file is tiny so we
    re-read on every call instead of caching.
    """

    async def get(self) -> Any: ...
    async def update(self, **fields: Any) -> Any: ...


# ── Auth / identity ──────────────────────────────────────────────────────────


@runtime_checkable
class AuthProviderProtocol(Protocol):
    """Identity verification adapter.

    The reference impl is :class:`mhc_desktop_deploy.impls.auth.mock.MockAuthProvider`
    (ships in the deploy package); enterprise customers substitute
    an LDAP / OAuth / OIDC adapter that implements the same surface.

    ``login`` returns ``(token, AuthUser)`` on success and ``None`` on
    bad credentials. ``resolve`` returns the principal for a live
    token or ``None`` for an unknown / expired one. ``logout``
    invalidates a token; subsequent ``resolve`` calls for it must
    return ``None``.
    """

    async def login(
        self, username: str, password: str
    ) -> tuple[str, AuthUser] | None: ...
    async def resolve(self, token: str) -> AuthUser | None: ...
    async def logout(self, token: str) -> None: ...


# ── Tool execution ──────────────────────────────────────────────────────────
#
# The kernel ships a thin "strategy registry" for tool execution:
# each :class:`ToolKind` (``local`` / ``script`` / ``remote``) is
# looked up in the deploy-provided registry and run by whichever
# executor the deploy plugged in. The kernel never decides HOW a
# tool of a given kind is invoked — that's a deploy concern.
#
# ``resolve`` returns an awaitable that yields string chunks (the
# same shape the chat handler consumes) plus an ``ok``/``error``
# summary on completion. ``None`` means "this kind is not wired in
# this deploy" — the chat handler treats that as "tool not callable
# in this build" and surfaces an actionable error to the model.


@runtime_checkable
class ToolExecutor(Protocol):
    """Strategy for executing one Tool call to completion.

    Implementations are async-context-manager-friendly but the
    registry contract is just ``execute``: the chat handler wraps
    each call in a cancel/timeout boundary of its own.
    """

    async def execute(
        self,
        tool: Tool,
        args: dict[str, Any],
        *,
        cancel_event: asyncio.Event | None = None,
        timeout: float = 15 * 60,
    ) -> "ToolExecution": ...


@dataclass
class ToolExecution:
    """Result of one ToolExecutor.execute call.

    Mirrors what the chat handler's tool path needs to emit:
    ``ok=True`` + ``chunks`` for a successful run; ``ok=False`` +
    ``error`` for a failure (timeout, cancel, exception). The chat
    handler streams each chunk as a ``tool_progress`` SSE event and
    the final state as ``tool_end``.
    """

    ok: bool
    chunks: list[str] = field(default_factory=list)
    error: str | None = None
    cancelled: bool = False


@runtime_checkable
class ToolExecutorRegistryProtocol(Protocol):
    """Maps a :class:`ToolKind` to its :class:`ToolExecutor`.

    The kernel calls :meth:`resolve` once per tool invocation. A
    return value of ``None`` (or a registry that returns ``None``
    for the kind) means the kind is not implemented in this deploy
    — the kernel surfaces a clear "kind not wired" error to the
    model.

    Deploys supply the default :class:`LocalToolExecutor` (which
    wraps the kernel's :func:`run_tool`); enterprises can swap
    that for a sandboxed subprocess runner, or add new kinds
    (``"wasm"``, ``"grpc"``) without touching the kernel.
    """

    def resolve(self, kind: str) -> ToolExecutor | None: ...


# ── Chat policy ─────────────────────────────────────────────────────────────
#
# Numeric limits that govern chat-loop behaviour — tool timeouts,
# per-skill inline budgets, max tool rounds, prefs size cap. These
# were all module-level constants in the kernel before; pulling
# them onto a deploy-injectable dataclass lets enterprises tighten
# the budgets for compliance without forking the kernel.


@dataclass(frozen=True)
class ChatPolicy:
    """Deploy-tunable numeric limits for the chat loop.

    Defaults match the previous module-level constants; deploy
    callers can pass a tighter copy (``ChatPolicy(tool_timeout_seconds=30)``)
    to enforce a stricter compliance ceiling.
    """

    # Local-tool execution ceiling. The kernel's :func:`run_tool`
    # raises :class:`asyncio.TimeoutError` past this; chat loop turns
    # that into a ``tool_end`` event with ``error="timeout"``.
    tool_timeout_seconds: float = 15 * 60
    # Per-skill inline file body budget (used by the chat loop when
    # inlining skill file contents into the system prompt).
    inline_file_max_bytes: int = 16 * 1024
    inline_skill_max_bytes: int = 64 * 1024
    # Cap on consecutive tool-call follow-up rounds. Hit this and the
    # loop stops asking the model for another turn (every emitted
    # call still executes).
    max_tool_rounds: int = 2000
    # Maximum size of the user-saved system-prompt addition. The
    # kernel rejects larger strings at the API boundary so a runaway
    # client can't balloon every chat request's token cost.
    system_prompt_addition_max_bytes: int = 8 * 1024


__all__ = [
    "AuthProviderProtocol",
    "AuthUser",
    "ChatPolicy",
    "MCPManagerProtocol",
    "MCPStoreProtocol",
    "MetricsRepositoryProtocol",
    "PrefsStoreProtocol",
    "Provider",
    "ProviderStoreProtocol",
    "Session",
    "SessionStoreProtocol",
    "Skill",
    "SkillStoreProtocol",
    "MCPServer",
    "StreamRegistryProtocol",
    "Tool",
    "ToolExecution",
    "ToolExecutor",
    "ToolExecutorRegistryProtocol",
    "ToolStoreProtocol",
]
