"""MCP subsystem.

Public surface:

* :class:`MCPServer` — config + tool catalog
* :class:`MCPStore` — disk-backed CRUD
* :class:`MCPManager` — subprocess + JSON-RPC client
* :class:`MCPError` — caller-facing error
* :class:`MCPSchemaTool` — minimal ``Tool`` whose only role is to expose
  the JSON schema to the LLM; the chat handler routes the resulting
  tool calls back to the manager itself.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, AsyncIterator, Iterable

from minimal_harness.types import ToolCall, ToolEvent

from mhc_desktop_backend.mcp.manager import MCPConnection, MCPError, MCPManager
from mhc_desktop_backend.mcp.models import MCPServer, slugify

if TYPE_CHECKING:  # pragma: no cover — type-check only
    from mhc_desktop_backend.protocols import MCPStoreProtocol

__all__ = [
    "MCPServer",
    "MCPConnection",
    "MCPError",
    "MCPManager",
    "MCPSchemaTool",
    "MCPStoreProtocol",
    "ToolCall",
    "ToolEvent",
    "slugify",
]


class MCPSchemaTool:
    """A ``Tool``-shaped object that only exposes the JSON schema.

    The LLM receives this in the ``tools=`` parameter; if it picks
    one, the resulting ``tool_calls`` are intercepted by the chat
    handler in :func:`api.chat._event_stream`, which calls back into
    :meth:`MCPManager.call_tool` itself rather than going through
    :meth:`Tool.execute`. We skip the executor route because the
    chat handler is a streaming SSE generator, not a long-running
    agent that can sit in an event loop draining ToolEvents.

    Implements the duck-typed surface that
    ``OpenAILLMProvider._chat`` / ``AnthropicLLMProvider._chat``
    poke at: ``to_schema`` / ``to_anthropic_schema``.
    """

    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        display_name: str = "",
    ) -> None:
        self.name = name
        self.description = description
        self.parameters = parameters
        self.display_name = display_name or name
        self.display_name_locale = None
        self.description_locale = None

    def to_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def to_anthropic_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters,
        }

    def resolve_display_name(self, locale: str = "") -> str:
        if locale and self.display_name_locale and locale in self.display_name_locale:
            return self.display_name_locale[locale]
        return self.display_name or self.name

    def resolve_description(self, locale: str = "") -> str:
        if locale and self.description_locale and locale in self.description_locale:
            return self.description_locale[locale]
        return self.description

    async def execute(
        self,
        args: dict[str, Any],
        tool_call: ToolCall,
        stop_event: Any,
    ) -> AsyncIterator[ToolEvent]:
        # Not used by the chat handler (which routes via the manager),
        # but required by the Tool Protocol so this object can also
        # flow through the standard agent path if we ever plug one in.
        if False:
            yield  # pragma: no cover
        return
        yield  # type: ignore[unreachable]


def mcp_tools_for(server: MCPServer) -> list[MCPSchemaTool]:
    """Build the ``MCPSchemaTool`` list for one MCP server using the
    persisted tool catalog."""
    out: list[MCPSchemaTool] = []
    for schema in server.tools:
        raw = str(schema.get("name") or "")
        if not raw:
            continue
        out.append(
            MCPSchemaTool(
                name=f"{server.slug}::{raw}",
                description=str(schema.get("description") or ""),
                parameters=schema.get("inputSchema")
                or {"type": "object", "properties": {}},
                display_name=f"{server.name}: {raw}",
            )
        )
    return out


async def collect_mcp_tools(
    manager: MCPManager,
    store: "MCPStoreProtocol",
    slugs: Iterable[str],
) -> tuple[list[MCPSchemaTool], list[str]]:
    """Gather tools from the requested slugs.

    Returns ``(tools, errors)``. Disabled or unknown slugs are
    skipped; connection failures don't abort the whole call \u2014 the
    chat handler yields a single ``error`` event listing them.
    """
    slugs_list = list(slugs)
    if not slugs_list:
        return [], []
    tools: list[MCPSchemaTool] = []
    errors: list[str] = []
    for slug in slugs_list:
        server = await store.get(slug)
        if server is None:
            errors.append(f"MCP '{slug}' not found")
            continue
        if not server.enabled:
            continue
        try:
            schemas = await manager.list_tools(server)
            server.tools = schemas
        except MCPError as e:
            errors.append(str(e))
            continue
        tools.extend(mcp_tools_for(server))
    return tools, errors
