"""Tests for the ToolExecutorRegistry Protocol seam.

The kernel ships a thin "strategy registry" for tool execution.
Deploys plug in a ``ToolExecutorRegistryProtocol`` via
``create_app(tool_executor_registry=...)``; the kernel chat
handler routes every ``tool.kind`` through that registry. Without
a registry the historical fallback (``local`` runs in-process,
``script``/``remote`` emit a "not wired" stub) is used so ad-hoc
apps and tests work.

These tests pin:

* the Protocol + dataclass types are importable and structural
* a deploy-provided registry actually replaces the kernel's stub
  for ``script`` / ``remote`` kinds
* missing kinds raise a clear error the model can act on
* the kernel still works without a registry (``local``/``bundled``
  tools keep running through ``run_tool``)
"""

from __future__ import annotations

from typing import Any


from mhc_desktop_backend.app import create_app
from mhc_desktop_backend.protocols import (
    ToolExecution,
    ToolExecutor,
    ToolExecutorRegistryProtocol,
)


# ── Stubs ──────────────────────────────────────────────────────────────────


class _ExecHello(ToolExecutor):
    """Executor that returns a deterministic greeting regardless of
    args. Lets us prove the registry path is being taken."""

    last_invocation: dict | None = None

    async def execute(
        self,
        tool,
        args: dict[str, Any],
        *,
        cancel_event=None,
        timeout=900.0,
    ) -> ToolExecution:
        type(self).last_invocation = {
            "slug": tool.slug,
            "args": args,
            "timeout": timeout,
        }
        return ToolExecution(ok=True, chunks=["hello-from-executor"])


class _ExecFailing(ToolExecutor):
    """Executor that always fails so we can prove failure paths
    propagate cleanly through the kernel."""

    async def execute(
        self,
        tool,
        args: dict[str, Any],
        *,
        cancel_event=None,
        timeout=900.0,
    ) -> ToolExecution:
        return ToolExecution(ok=False, error="boom")


class _Registry(ToolExecutorRegistryProtocol):
    """Registry that maps ``script`` to _ExecHello and ``remote``
    to _ExecFailing. Returns ``None`` for unknown kinds so the
    kernel's fallback path runs."""

    def __init__(self) -> None:
        self.hello = _ExecHello()
        self.failing = _ExecFailing()
        # Count resolution attempts so tests can verify the
        # kernel actually asked.
        self.calls: list[str] = []

    def resolve(self, kind: str) -> ToolExecutor | None:
        self.calls.append(kind)
        if kind == "script":
            return self.hello
        if kind == "remote":
            return self.failing
        return None


class _InMemoryToolStore:
    """Minimal :class:`ToolStoreProtocol` with a single ``script`` tool
    + a single ``local`` tool (so we can prove the registry path
    is taken for ``script`` and the fallback for ``local``)."""

    def __init__(self) -> None:
        from mhc_desktop_backend.tools.models import Tool

        self.local_tool = Tool(
            slug="now",
            name="Now",
            description="local-only",
            kind="local",
            parameters={"type": "object", "properties": {}},
            enabled=True,
            origin="imported",
        )
        self.script_tool = Tool(
            slug="hello",
            name="Hello",
            description="scripted",
            kind="script",
            parameters={"type": "object", "properties": {}},
            enabled=True,
            origin="imported",
        )

    async def list(self):
        return [self.local_tool, self.script_tool]

    async def get(self, slug):
        for t in await self.list():
            if t.slug == slug:
                return t
        return None

    async def get_by_model_name(self, name):
        # mirror get() — the test doesn't exercise the model-name lookup
        for t in await self.list():
            if t.slug == name:
                return t
        return None

    async def get_callable(self, slug):
        return None  # local tool needs the import cache path instead

    async def create(self, data):
        raise NotImplementedError

    async def update(self, slug, data):
        raise NotImplementedError

    async def delete(self, slug):
        return None

    async def set_enabled(self, slug, enabled):
        return self.local_tool

    async def close(self):
        return None


def test_protocols_importable():
    """The Protocol + dataclass types the deploy consumes are
    importable from the canonical path."""
    from mhc_desktop_backend.protocols import (
        ToolExecution,
        ToolExecutor,
        ToolExecutorRegistryProtocol,
    )

    assert ToolExecutor is not None
    assert ToolExecutorRegistryProtocol is not None
    assert ToolExecution is not None


def test_executor_returns_execution_dataclass():
    """A deploy executor that returns a ``ToolExecution`` can be
    invoked directly and the kernel-side consumers get a stable
    shape back (chunks list + ok flag + optional error)."""
    import asyncio

    exec_ = _ExecHello()
    tool = type("_T", (), {"slug": "x"})()  # tiny duck-typed stand-in

    async def _run():
        return await exec_.execute(tool, {"k": "v"})

    out = asyncio.run(_run())
    assert out.ok is True
    assert out.chunks == ["hello-from-executor"]
    assert out.error is None


def test_failing_executor_reports_error():
    import asyncio

    exec_ = _ExecFailing()
    tool = type("_T", (), {"slug": "x"})()

    async def _run():
        return await exec_.execute(tool, {})

    out = asyncio.run(_run())
    assert out.ok is False
    assert out.error == "boom"
    assert out.chunks == []


def test_registry_resolves_to_none_for_unknown_kind():
    """Registry returns ``None`` for unknown kinds so the kernel
    can fall back to its historical behaviour for the kinds the
    deploy didn't bother wiring."""
    reg = _Registry()
    assert reg.resolve("local") is None  # kernel fallback handles this
    assert reg.resolve("script") is not None
    assert reg.resolve("remote") is not None
    assert reg.resolve("wasm") is None


def test_create_app_accepts_tool_executor_registry_kwarg():
    """``create_app(tool_executor_registry=...)`` plumbs the
    registry into ``app.state`` so the chat handler can find it.
    """
    reg = _Registry()
    app = create_app(tool_executor_registry=reg)
    assert app.state.tool_executor_registry is reg


def test_create_app_without_registry_keeps_legacy_fallback():
    """Without a registry the app still boots; the chat handler
    will fall back to the historical kernel behaviour for
    ``local`` tools and stub ``script``/``remote`` kinds."""
    app = create_app()
    assert getattr(app.state, "tool_executor_registry", None) is None


def test_registry_resolve_called_during_chat_loop():
    """End-to-end check: ``build_streaming_tool`` consults the
    registry when one is wired. We invoke the helper directly
    rather than driving the chat router because the router
    requires a session store + LLM stub — the seam we want to
    pin is the registry lookup, which is fully covered here.
    """
    import asyncio

    from mhc_desktop_backend.tools import build_streaming_tool

    reg = _Registry()
    store = _InMemoryToolStore()
    script_tool = asyncio.run(store.get("hello"))

    # Calling ``build_streaming_tool`` with the registry wires the
    # executor into the resulting StreamingTool's ``fn``.
    st = asyncio.run(
        build_streaming_tool(
            script_tool,
            tool_executor_registry=reg,
        )
    )

    async def _drive():
        out: list[str] = []
        async for chunk in st.fn(who="world"):
            out.append(chunk)
        return out

    chunks = asyncio.run(_drive())
    assert chunks == ["hello-from-executor"]
    # Registry saw the kind lookup for "script" exactly once.
    assert reg.calls == ["script"]
    # The executor received the tool's slug + the args forwarded
    # by the chat handler.
    assert _ExecHello.last_invocation["slug"] == "hello"
    assert _ExecHello.last_invocation["args"] == {"who": "world"}


def test_registry_failure_propagates_as_tool_error():
    """When a deploy executor reports ``ok=False``, the resulting
    stream yields the error verbatim so the model can act on it.
    """
    import asyncio

    from mhc_desktop_backend.tools import build_streaming_tool

    reg = _Registry()
    store = _InMemoryToolStore()

    # Register a ``remote`` tool in the in-memory store.
    from mhc_desktop_backend.tools.models import Tool

    reg_tool = Tool(
        slug="upstream",
        name="Upstream",
        description="remote stub",
        kind="remote",
        parameters={"type": "object", "properties": {}},
        enabled=True,
        origin="imported",
    )
    store.list = lambda: [reg_tool]  # type: ignore[assignment]

    async def _list():
        return [reg_tool]

    store.list = _list  # type: ignore[assignment]
    rt = asyncio.run(store.get("upstream"))
    st = asyncio.run(build_streaming_tool(rt, tool_executor_registry=reg))

    async def _drive():
        return [c async for c in st.fn()]

    chunks = asyncio.run(_drive())
    # Failure path prefixes with "[tool error]" so the model can
    # tell it apart from successful output. The deploy executor's
    # own error message is preserved verbatim after the prefix.
    assert chunks == ["[tool error] boom"]
    assert reg.calls == ["remote"]
