"""MCP subsystem smoke tests.

Covers the store CRUD path and the schema-tool shape. Live MCP
subprocess roundtrips are out of scope here — the installer no
longer ships a bundled dummy server, and customers provide their
own MCPs through the bulk-import flow.
"""

from __future__ import annotations

import asyncio

import pytest

from mhc_desktop_backend.mcp import (
    MCPServer,
    MCPSchemaTool,
    mcp_tools_for,
)
from mhc_desktop_backend.mcp.manager import MCPError
from mhc_desktop_deploy.impls.file_stores.mcp_store import MCPStore


# ── Store CRUD ────────────────────────────────────────────────────────────


@pytest.fixture
def store(tmp_path):
    return MCPStore(mcp_dir=tmp_path / "mcp", state_file=tmp_path / "st.json")


def test_store_upsert_creates_dir_and_config(store):
    async def main():
        srv = await store.upsert(
            slug="",
            name="My MCP",
            description="",
            command="echo",
            args=["hello"],
            env={},
            origin="imported",
        )
        assert srv.slug == "my-mcp"
        assert (store._dir / "my-mcp" / "config.json").is_file()
        # Re-fetch and confirm.
        srv2 = await store.get("my-mcp")
        assert srv2 is not None
        assert srv2.name == "My MCP"
        assert srv2.command == "echo"
        assert srv2.args == ["hello"]

    asyncio.run(main())


def test_store_set_enabled_persists(store):
    async def main():
        await store.upsert(
            slug="tog",
            name="tog",
            description="",
            command="echo",
            args=[],
            env={},
        )
        await store.set_enabled("tog", False)
        srv = await store.get("tog")
        assert srv.enabled is False
        await store.set_enabled("tog", True)
        srv = await store.get("tog")
        assert srv.enabled is True

    asyncio.run(main())


def test_store_delete_removes_dir_and_state(store):
    async def main():
        await store.upsert(
            slug="rm",
            name="rm",
            description="",
            command="echo",
            args=[],
            env={},
        )
        await store.delete("rm")
        assert await store.get("rm") is None
        assert "rm" not in store._load_state()

    asyncio.run(main())


def test_store_upsert_validates_args_and_env(store):
    async def main():
        with pytest.raises(MCPError):
            await store.upsert(
                slug="bad-args",
                name="bad",
                description="",
                command="echo",
                args=["ok", 123],  # type: ignore[list-item]
                env={},
            )
        with pytest.raises(MCPError):
            await store.upsert(
                slug="bad-env",
                name="bad",
                description="",
                command="echo",
                args=[],
                env={"k": 1},  # type: ignore[dict-item]
            )

    asyncio.run(main())


# ── MCPSchemaTool ─────────────────────────────────────────────────────────


def test_schema_tool_openai_shape():
    t = MCPSchemaTool(
        name="dummy::add",
        description="Add",
        parameters={"type": "object", "properties": {"a": {"type": "integer"}}},
    )
    s = t.to_schema()
    assert s == {
        "type": "function",
        "function": {
            "name": "dummy::add",
            "description": "Add",
            "parameters": {"type": "object", "properties": {"a": {"type": "integer"}}},
        },
    }


def test_schema_tool_anthropic_shape():
    t = MCPSchemaTool(
        name="dummy::echo",
        description="Echo",
        parameters={"type": "object", "properties": {"text": {"type": "string"}}},
    )
    s = t.to_anthropic_schema()
    assert s == {
        "name": "dummy::echo",
        "description": "Echo",
        "input_schema": {"type": "object", "properties": {"text": {"type": "string"}}},
    }


def test_mcp_tools_for_namespaces_and_skips_empty_names():
    server = MCPServer(
        slug="srv",
        name="Srv",
        description="",
        command="x",
        args=[],
        tools=[
            {"name": "add", "description": "Add", "inputSchema": {"type": "object"}},
            {"name": "", "description": "Skip", "inputSchema": {"type": "object"}},
        ],
    )
    out = mcp_tools_for(server)
    assert [t.name for t in out] == ["srv::add"]
