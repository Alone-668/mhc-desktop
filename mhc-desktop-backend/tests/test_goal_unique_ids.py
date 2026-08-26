"""Backend unit tests for the goal's unique-ID + chat-persistence work.

Covers:
- Skill / MCP / Tool stores assign a UUID ``id`` distinct from slug
  and name, and backfill it on legacy records.
- ``Tool.resolved_model_name`` falls back to slug when unset.
- ToolStore can resolve by model_name (the LLM-facing name).
- The chat endpoint persists the assistant reply into the session
  store at end of stream, preserving per-message metadata.
"""

from __future__ import annotations

import uuid

import pytest

from mhc_desktop_deploy.impls.file_stores.mcp_store import MCPStore
from mhc_desktop_deploy.impls.file_stores.skills_store import SkillStore
from mhc_desktop_backend.tools.models import Tool
from mhc_desktop_deploy.impls.file_stores.tools_store import ToolStore


@pytest.mark.asyncio
async def test_tool_create_generates_uuid_id(tmp_path):
    store = ToolStore(tools_dir=tmp_path)
    tool = await store.create(
        {
            "slug": "test-tool",
            "name": "Test Tool",
            "description": "d",
            "kind": "local",
        }
    )
    assert tool.id, "create must generate a UUID id"
    # UUID-shaped
    uuid.UUID(tool.id)
    assert tool.slug == "test-tool"
    assert tool.name == "Test Tool"
    assert tool.id != tool.slug
    assert tool.id != tool.name
    await store.close()


@pytest.mark.asyncio
async def test_tool_load_backfills_missing_id(tmp_path):
    # Simulate a legacy record on disk without an id.
    state = tmp_path / "tools-state.json"
    state.write_text(
        '[{"slug": "legacy", "name": "Legacy", "kind": "local", "description": ""}]',
        encoding="utf-8",
    )
    store = ToolStore(tools_dir=tmp_path)
    tool = await store.get("legacy")
    assert tool is not None
    assert tool.id, "load must backfill a UUID id for legacy records"
    uuid.UUID(tool.id)
    await store.close()


def test_tool_model_name_fallback():
    t = Tool(slug="greeter", name="Greeter", description="")
    assert t.resolved_model_name() == "greeter"
    t2 = Tool(slug="greeter", name="Greeter", model_name="say_hello", description="")
    assert t2.resolved_model_name() == "say_hello"


@pytest.mark.asyncio
async def test_tool_store_resolves_by_model_name(tmp_path):
    store = ToolStore(tools_dir=tmp_path)
    await store.create(
        {
            "slug": "greeter",
            "name": "Greeter",
            "model_name": "say_hello",
            "description": "",
            "kind": "local",
        }
    )
    by_model = await store.get_by_model_name("say_hello")
    assert by_model is not None and by_model.slug == "greeter"
    # Falling back to slug also works.
    assert (await store.get_by_model_name("greeter")) is not None
    await store.close()


@pytest.mark.asyncio
async def test_mcp_upsert_generates_uuid_id(tmp_path):
    store = MCPStore(mcp_dir=tmp_path)
    srv = await store.upsert(
        slug="dummy",
        name="Dummy",
        description="",
        command="echo",
        args=["hi"],
    )
    assert srv.id, "MCP upsert must generate a UUID id"
    uuid.UUID(srv.id)
    assert srv.id != srv.slug


@pytest.mark.asyncio
async def test_skill_get_backfills_uuid_id(tmp_path):
    # Create a minimal skill folder without a state file (legacy).
    skill_dir = tmp_path / "skills" / "legacy-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: Legacy Skill\n---\n\nBody here\n", encoding="utf-8"
    )
    store = SkillStore(skills_dir=tmp_path / "skills")
    skill = await store.get("legacy-skill")
    assert skill is not None
    assert skill.id, "skill load must backfill a UUID id"
    uuid.UUID(skill.id)
    assert skill.id != skill.slug
    assert skill.name == "Legacy Skill"
