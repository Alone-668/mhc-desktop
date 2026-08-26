"""Tools subsystem — parallels Skills and MCP.

Public surface:

* :class:`Tool` — config + parameters schema (see :mod:`tools.models`)
* :class:`ToolStore` — disk-backed CRUD on user tools
* :class:`ToolStoreError` — caller-facing error type
* :func:`run_tool` — executes a local tool with timeout + cancel
* :func:`import_local_tool` — compiles + caches a Python source string
* :func:`build_streaming_tool` — turns a :class:`Tool` into a
  minimal-harness ``StreamingTool`` the LLM can call
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, AsyncIterator

from minimal_harness.tool.base import StreamingTool

from mhc_desktop_backend.tools.errors import ToolStoreError
from mhc_desktop_backend.tools.imports import (
    DEFAULT_TOOL_TIMEOUT_SECONDS,
    evict_cached_local,
    get_cached_local,
    import_local_tool,
    run_tool,
)
from mhc_desktop_backend.tools.models import Tool, slugify

if TYPE_CHECKING:
    from mhc_desktop_backend.protocols import ToolExecutorRegistryProtocol

# ``ToolStore`` (the concrete class) moved to
# ``mhc_desktop_deploy.impls.file_stores.tools_store``. Callers
# should depend on :class:`mhc_desktop_backend.protocols.ToolStoreProtocol`
# instead — the kernel never imports the concrete class.
__all__ = [
    "Tool",
    "ToolStoreError",
    "import_local_tool",
    "run_tool",
    "evict_cached_local",
    "get_cached_local",
    "DEFAULT_TOOL_TIMEOUT_SECONDS",
    "StreamingTool",
    "build_streaming_tool",
    "build_tool_event_stream",
    "slugify",
]


async def build_streaming_tool(
    tool: Tool,
    *,
    cancel_event: asyncio.Event | None = None,
    timeout: float = DEFAULT_TOOL_TIMEOUT_SECONDS,
    tool_executor_registry: "ToolExecutorRegistryProtocol | None" = None,
):
    """Build a minimal-harness ``StreamingTool`` from a :class:`Tool`
    config.

    Execution strategy:

    * If a deploy-provided :class:`ToolExecutorRegistryProtocol`
      resolves ``tool.kind`` to a non-None executor, the resulting
      ``StreamingTool``'s ``fn`` delegates to that executor. The
      deploy owns the actual call semantics — sandboxing,
      subprocess lifecycle, network call, whatever.
    * Otherwise the kernel falls back to the historical path:
      ``local``/``bundled`` tools wrap their import cache callable
      via :func:`run_tool`; ``script``/``remote`` kinds yield a
      "not wired in this build" stub (the original behaviour, kept
      so ad-hoc / test apps without a deploy executor still work).

    The chat handler then passes the resulting list as the
    ``tools=`` argument of ``llm.chat(messages, tools=[...])`` the
    same way it does for MCP tools.
    """
    # 1. Deploy-provided executor wins — the registry's ``resolve``
    # is the canonical seam for "how is tool X actually executed?".
    # We consult it FIRST so a deploy with a real script/remote
    # executor never falls through to the kernel's "not wired" stub.
    executor = None
    if tool_executor_registry is not None:
        executor = tool_executor_registry.resolve(tool.kind)
    if executor is not None:

        async def _via_executor(**kwargs: Any) -> AsyncIterator[str]:
            execution = await executor.execute(
                tool,
                kwargs,
                cancel_event=cancel_event,
                timeout=timeout,
            )
            for chunk in execution.chunks:
                yield chunk
            # Failure surfaces as a single "tool error" chunk so the
            # chat handler can route it through ``tool_end``. We
            # don't raise here — the streaming-tool contract is an
            # async-iterator-of-strings, not an exception channel.
            if not execution.ok and execution.error:
                yield f"[tool error] {execution.error}"
            if execution.cancelled:
                yield "[tool error] tool cancelled by user"

        return StreamingTool(
            name=tool.resolved_model_name(),
            display_name=tool.name,
            description=tool.description,
            parameters=tool.parameters or {"type": "object", "properties": {}},
            fn=_via_executor,
        )

    # 2. No deploy executor — historical kernel path. The callable
    # resolution short-circuits for non-``local`` kinds because the
    # import-cache lookup is local-only.
    fn = await _resolve_callable(tool)
    if fn is None:
        # The tool is registered in the store (so the model sees it)
        # but its Python source isn't loaded in *this* backend process.
        # The most common cause is that the user re-imported the tool
        # via bulk-import on a uvicorn worker that WatchFiles then
        # hot-reloaded — the new worker has a fresh ``_LOCAL_CACHE``.
        # Surface this with enough context that the model can tell
        # the user what to do, instead of pretending the tool ran.
        msg = (
            f"[tool error] tool='{tool.slug}' callable not loaded in this backend process. "
            "The tool is registered but its Python source wasn't imported "
            "into the worker handling this chat. Ask the user to delete "
            "the tool and re-import it, or restart the backend."
        )

        async def _missing(**_: Any) -> AsyncIterator[str]:
            yield msg

        return StreamingTool(
            name=tool.resolved_model_name(),
            display_name=tool.name,
            description=tool.description,
            parameters=tool.parameters or {"type": "object", "properties": {}},
            fn=_missing,
        )

    # No deploy executor — fall back to the historical kernel path
    # for ``local``/``bundled`` tools, and the "not wired" stub
    # for ``script``/``remote`` (preserves the original behaviour
    # for ad-hoc apps without a registry).
    if tool.kind in ("script", "remote"):

        async def _stub(**_: Any) -> AsyncIterator[str]:
            yield f"({tool.kind} execution not wired in this build)"

        return StreamingTool(
            name=tool.resolved_model_name(),
            display_name=tool.name,
            description=tool.description,
            parameters=tool.parameters or {"type": "object", "properties": {}},
            fn=_stub,
        )

    async def _wrapped(**kwargs: Any) -> AsyncIterator[str]:
        async for chunk in run_tool(
            fn,
            kwargs,
            timeout=timeout,
            cancel_event=cancel_event,
        ):
            yield chunk

    return StreamingTool(
        name=tool.resolved_model_name(),
        display_name=tool.name,
        description=tool.description,
        parameters=tool.parameters or {"type": "object", "properties": {}},
        fn=_wrapped,
    )


async def _resolve_callable(tool: Tool):
    """Return the raw Python callable for a local tool.

    User local tools come from the ``imports`` module's process-local
    cache; everything else has no callable in this build.

    On a cache miss (backend restarted / uvicorn reloaded between
    import and call) we lazily re-import from the on-disk copy at
    ``~/.mhc-desktop/tools/<slug>/tool.py``. That copy is written at
    bulk-import time (see api/tools.py), so the tool survives process
    restarts just like skills / MCP configs do.
    """
    if tool.kind == "local":
        fn = get_cached_local(tool.slug)
        if fn is not None:
            return fn
        # Cache miss → try the on-disk copy. This is the common case
        # after a backend restart: the store index survives (it's a
        # JSON file) but the process-local callable cache doesn't.
        from mhc_desktop_backend.tools.imports import import_tool_from_disk

        return await import_tool_from_disk(tool.slug, tool.source_path)


async def build_tool_event_stream(
    tool: Tool,
    args: dict[str, Any],
    *,
    cancel_event: asyncio.Event | None = None,
    timeout: float = DEFAULT_TOOL_TIMEOUT_SECONDS,
) -> AsyncIterator[str]:
    """Yield the strings a streaming tool produces. Used by the
    chat handler's tool-execution path so it can route each chunk
    into a ``ToolProgress`` / ``ToolEnd`` SSE event without going
    through minimal-harness's full agent loop.
    """
    fn = await _resolve_callable(tool)
    if fn is None:
        # Mirror the actionable message from build_streaming_tool —
        # both paths can be reached depending on whether the caller
        # wraps in a StreamingTool first.
        yield (
            f"[tool error] tool='{tool.slug}' callable not loaded in this backend process. "
            "The tool is registered but its Python source wasn't imported "
            "into the worker handling this chat. Ask the user to delete "
            "the tool and re-import it, or restart the backend."
        )
        return
    async for chunk in run_tool(
        fn,
        args,
        timeout=timeout,
        cancel_event=cancel_event,
    ):
        yield chunk
