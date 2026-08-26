"""End-to-end tests for the bundled-content materializer.

These tests pin the behaviour of
:mod:`mhc_desktop_backend.content_packs` against the file-backed
reference stores. They cover both the boot-time
``materialize_bundled`` (used by ``create_app()`` lifespan startup)
and the per-domain ``bulk_install_*`` helpers that back the
``/api/v1/{skills,tools,mcp}/import-bulk`` routes.

Key invariants we want to keep:

1. **Idempotent boot**: launching the same packaged installer twice
   doesn't duplicate skills / tools / MCPs.
2. **User customizations preserved**: a skill body edited by the
   user survives the next ``materialize_bundled`` call (the bundled
   copy is skipped, not overwritten, because ``overwrite=False``).
3. **Manual import still works**: the ``bulk_install_*`` helpers
   used by the routes behave identically to the old inline
   implementations.
4. **Broken units don't crash the whole batch**: a single malformed
   ``tool.py`` is reported as an error; the rest still install.

All tests put source content under ``tmp_path / "pack"`` and the
stores under ``tmp_path / "store"`` so the recursive scanners don't
walk into the store's own copies and double-count.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mhc_desktop_backend.content_packs import (
    bulk_install_mcps,
    bulk_install_skills,
    bulk_install_tools,
    materialize_bundled,
)
from mhc_desktop_deploy.impls.file_stores.mcp_store import MCPStore
from mhc_desktop_deploy.impls.file_stores.skills_store import SkillStore
from mhc_desktop_deploy.impls.file_stores.tools_store import ToolStore


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def pack(tmp_path: Path) -> Path:
    """Where bundled content lives — separate from the store."""
    p = tmp_path / "pack"
    p.mkdir()
    return p


@pytest.fixture
def skill_store(tmp_path: Path) -> SkillStore:
    return SkillStore(
        skills_dir=tmp_path / "store" / "skills",
        state_file=tmp_path / "store" / "skills-state.json",
    )


@pytest.fixture
def tool_store(tmp_path: Path) -> ToolStore:
    return ToolStore(tools_dir=tmp_path / "store" / "tools")


@pytest.fixture
def mcp_store(tmp_path: Path) -> MCPStore:
    return MCPStore(mcp_dir=tmp_path / "store" / "mcp")


def _write_skill(
    folder: Path, *, name: str | None = None, description: str = "demo"
) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    nm = name or folder.name
    (folder / "SKILL.md").write_text(
        "---\n"
        f"name: {nm}\n"
        f"description: {description}\n"
        "version: 0.1.0\n"
        "---\n\n"
        f"# {nm}\n\nbody\n",
        encoding="utf-8",
    )


def _write_tool(
    folder: Path,
    *,
    name: str | None = None,
    source: str | None = None,
) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    src = (
        source
        if source is not None
        else ('async def tool_run(**kwargs):\n    yield f"hello from {kwargs!r}"\n')
    )
    (folder / "tool.py").write_text(src, encoding="utf-8")
    (folder / "manifest.json").write_text(
        json.dumps(
            {
                "name": name or folder.name,
                "description": f"tool {folder.name}",
                "parameters": {"type": "object", "properties": {}},
            }
        ),
        encoding="utf-8",
    )


def _write_mcp(folder: Path, *, name: str = "stdio", command: str = "npx") -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "config.json").write_text(
        json.dumps(
            {
                "name": name,
                "command": command,
                "args": ["-y", f"@example/{folder.name}"],
                "description": f"mcp {folder.name}",
                "env": {},
            }
        ),
        encoding="utf-8",
    )


# ── bulk_install_skills ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bulk_install_skills_walks_recursively(
    pack: Path, skill_store: SkillStore
) -> None:
    _write_skill(pack / "category-a" / "skill-a")
    _write_skill(pack / "category-a" / "skill-b")
    _write_skill(pack / "skill-c")  # direct child

    summary = await bulk_install_skills(pack, skill_store)

    assert len(summary["installed"]) == 3
    assert summary["skipped"] == []
    assert summary["errors"] == []
    slugs = {entry["slug"] for entry in summary["installed"]}
    assert slugs == {"skill-a", "skill-b", "skill-c"}


@pytest.mark.asyncio
async def test_bulk_install_skills_skips_existing_by_default(
    pack: Path, skill_store: SkillStore
) -> None:
    _write_skill(pack / "skill-a")

    s1 = await bulk_install_skills(pack, skill_store)
    assert len(s1["installed"]) == 1
    assert s1["skipped"] == []

    s2 = await bulk_install_skills(pack, skill_store)
    assert s2["installed"] == []
    assert len(s2["skipped"]) == 1
    assert s2["errors"] == []

    assert len(await skill_store.list()) == 1


@pytest.mark.asyncio
async def test_bulk_install_skills_overwrite_true_replaces(
    pack: Path, skill_store: SkillStore
) -> None:
    _write_skill(pack / "skill-a", description="original")
    await bulk_install_skills(pack, skill_store)

    _write_skill(pack / "skill-a", description="updated")
    s2 = await bulk_install_skills(pack, skill_store, overwrite=True)
    assert len(s2["installed"]) == 1
    skill = await skill_store.get("skill-a")
    assert skill is not None
    assert skill.description == "updated"


@pytest.mark.asyncio
async def test_bulk_install_skills_origin_is_bundled(
    pack: Path, skill_store: SkillStore
) -> None:
    _write_skill(pack / "skill-a")
    await bulk_install_skills(pack, skill_store, origin="bundled")
    skill = await skill_store.get("skill-a")
    assert skill is not None
    assert skill.origin == "bundled"


@pytest.mark.asyncio
async def test_bulk_install_skills_missing_root_records_error(
    tmp_path: Path, skill_store: SkillStore
) -> None:
    summary = await bulk_install_skills(tmp_path / "does-not-exist", skill_store)
    assert summary["installed"] == []
    assert summary["skipped"] == []
    assert len(summary["errors"]) == 1
    assert summary["errors"][0]["error"] == "not a directory"


@pytest.mark.asyncio
async def test_bulk_install_skills_bad_frontmatter_is_error(
    pack: Path, skill_store: SkillStore
) -> None:
    bad = pack / "skill-bad"
    bad.mkdir()
    (bad / "SKILL.md").write_text("just markdown, no frontmatter", encoding="utf-8")
    summary = await bulk_install_skills(pack, skill_store)
    assert summary["installed"] == []
    assert len(summary["errors"]) == 1
    assert "frontmatter" in summary["errors"][0]["error"].lower()


# ── bulk_install_tools ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bulk_install_tools_installs_with_manifest(
    pack: Path, tool_store: ToolStore
) -> None:
    _write_tool(pack / "echo-tool", name="Echo")

    summary = await bulk_install_tools(pack, tool_store)
    assert len(summary["installed"]) == 1
    assert summary["errors"] == []

    tool = await tool_store.get("echo-tool")
    assert tool is not None
    assert tool.name == "Echo"
    assert tool.origin == "imported"
    assert Path(tool.source_path).exists()
    assert (
        Path(tool.source_path)
        .read_text(encoding="utf-8")
        .startswith("async def tool_run")
    )


@pytest.mark.asyncio
async def test_bulk_install_tools_origin_bundled(
    pack: Path, tool_store: ToolStore
) -> None:
    _write_tool(pack / "echo-tool")
    await bulk_install_tools(pack, tool_store, origin="bundled")
    tool = await tool_store.get("echo-tool")
    assert tool is not None and tool.origin == "bundled"


@pytest.mark.asyncio
async def test_bulk_install_tools_skips_existing(
    pack: Path, tool_store: ToolStore
) -> None:
    _write_tool(pack / "echo-tool")
    await bulk_install_tools(pack, tool_store)
    s2 = await bulk_install_tools(pack, tool_store)
    assert s2["installed"] == []
    assert len(s2["skipped"]) == 1


@pytest.mark.asyncio
async def test_bulk_install_tools_overwrite_replaces(
    pack: Path, tool_store: ToolStore
) -> None:
    _write_tool(pack / "echo-tool", source="async def tool_run(**k):\n    yield 'a'\n")
    await bulk_install_tools(pack, tool_store)
    _write_tool(pack / "echo-tool", source="async def tool_run(**k):\n    yield 'b'\n")
    s2 = await bulk_install_tools(pack, tool_store, overwrite=True)
    assert len(s2["installed"]) == 1
    tool = await tool_store.get("echo-tool")
    assert tool is not None
    assert (
        Path(tool.source_path).read_text(encoding="utf-8").strip().endswith("yield 'b'")
    )


@pytest.mark.asyncio
async def test_bulk_install_tools_broken_tool_records_error(
    pack: Path, tool_store: ToolStore
) -> None:
    bad = pack / "broken-tool"
    bad.mkdir()
    (bad / "tool.py").write_text("def not_async def tool_run", encoding="utf-8")
    (bad / "manifest.json").write_text("{}", encoding="utf-8")

    _write_tool(pack / "good-tool")

    summary = await bulk_install_tools(pack, tool_store)
    assert len(summary["installed"]) == 1
    assert len(summary["errors"]) == 1
    assert "broken-tool" in summary["errors"][0]["path"]


# ── bulk_install_mcps ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bulk_install_mcps_upserts_each_config(
    pack: Path, mcp_store: MCPStore
) -> None:
    _write_mcp(pack / "fs-mcp", name="fs")
    _write_mcp(pack / "git-mcp", name="git")

    summary = await bulk_install_mcps(pack, mcp_store)
    assert len(summary["installed"]) == 2

    all_mcps = await mcp_store.list()
    slugs = {m.slug for m in all_mcps}
    assert slugs == {"fs-mcp", "git-mcp"}


@pytest.mark.asyncio
async def test_bulk_install_mcps_origin_bundled(
    pack: Path, mcp_store: MCPStore
) -> None:
    _write_mcp(pack / "fs-mcp")
    await bulk_install_mcps(pack, mcp_store, origin="bundled")
    srv = await mcp_store.get("fs-mcp")
    assert srv is not None and srv.origin == "bundled"


@pytest.mark.asyncio
async def test_bulk_install_mcps_skips_existing(
    pack: Path, mcp_store: MCPStore
) -> None:
    _write_mcp(pack / "fs-mcp")
    await bulk_install_mcps(pack, mcp_store)

    s2 = await bulk_install_mcps(pack, mcp_store)
    assert s2["installed"] == []
    assert len(s2["skipped"]) == 1


@pytest.mark.asyncio
async def test_bulk_install_mcps_bad_config_is_error(
    pack: Path, mcp_store: MCPStore
) -> None:
    bad = pack / "broken-mcp"
    bad.mkdir()
    (bad / "config.json").write_text("{not json", encoding="utf-8")
    summary = await bulk_install_mcps(pack, mcp_store)
    assert summary["installed"] == []
    assert len(summary["errors"]) == 1


# ── materialize_bundled (the boot-time entry point) ────────────────


@pytest.mark.asyncio
async def test_materialize_bundled_no_op_when_root_missing(
    tmp_path: Path,
    skill_store: SkillStore,
    tool_store: ToolStore,
    mcp_store: MCPStore,
) -> None:
    summary = await materialize_bundled(
        content_root=tmp_path / "does-not-exist",
        skill_store=skill_store,
        tool_store=tool_store,
        mcp_store=mcp_store,
    )
    for domain in ("skills", "tools", "mcp"):
        assert summary[domain] == {"installed": [], "skipped": [], "errors": []}
    assert await skill_store.list() == []
    assert await tool_store.list() == []
    assert await mcp_store.list() == []


@pytest.mark.asyncio
async def test_materialize_bundled_none_root_is_noop(
    skill_store: SkillStore,
    tool_store: ToolStore,
    mcp_store: MCPStore,
) -> None:
    summary = await materialize_bundled(
        content_root=None,
        skill_store=skill_store,
        tool_store=tool_store,
        mcp_store=mcp_store,
    )
    assert summary == {
        "skills": {"installed": [], "skipped": [], "errors": []},
        "tools": {"installed": [], "skipped": [], "errors": []},
        "mcp": {"installed": [], "skipped": [], "errors": []},
    }


@pytest.mark.asyncio
async def test_materialize_bundled_full_pipeline(
    pack: Path,
    skill_store: SkillStore,
    tool_store: ToolStore,
    mcp_store: MCPStore,
) -> None:
    """End-to-end: a realistic content pack layout installs across all three stores."""
    _write_skill(pack / "skills" / "create-skill")
    _write_tool(pack / "tools" / "echo")
    _write_mcp(pack / "mcp" / "fs")

    summary = await materialize_bundled(
        content_root=pack,
        skill_store=skill_store,
        tool_store=tool_store,
        mcp_store=mcp_store,
        origin="bundled",
    )
    assert len(summary["skills"]["installed"]) == 1
    assert len(summary["tools"]["installed"]) == 1
    assert len(summary["mcp"]["installed"]) == 1
    # Verify origin is "bundled" so we can tell apart from manually-imported.
    assert (await skill_store.get("create-skill")).origin == "bundled"
    assert (await tool_store.get("echo")).origin == "bundled"
    assert (await mcp_store.get("fs")).origin == "bundled"


@pytest.mark.asyncio
async def test_materialize_bundled_is_idempotent(
    pack: Path,
    skill_store: SkillStore,
    tool_store: ToolStore,
    mcp_store: MCPStore,
) -> None:
    """Second run must not duplicate or overwrite anything.

    Run 1: install everything. Run 2: zero installs, all skipped —
    the user-data state is unchanged.
    """
    _write_skill(pack / "skills" / "skill-a")
    _write_tool(pack / "tools" / "echo")
    _write_mcp(pack / "mcp" / "fs")

    s1 = await materialize_bundled(
        content_root=pack,
        skill_store=skill_store,
        tool_store=tool_store,
        mcp_store=mcp_store,
    )
    assert len(s1["skills"]["installed"]) == 1
    assert len(s1["tools"]["installed"]) == 1
    assert len(s1["mcp"]["installed"]) == 1

    s2 = await materialize_bundled(
        content_root=pack,
        skill_store=skill_store,
        tool_store=tool_store,
        mcp_store=mcp_store,
    )
    assert s2["skills"]["installed"] == []
    assert len(s2["skills"]["skipped"]) == 1
    assert s2["tools"]["installed"] == []
    assert len(s2["tools"]["skipped"]) == 1
    assert s2["mcp"]["installed"] == []
    assert len(s2["mcp"]["skipped"]) == 1


@pytest.mark.asyncio
async def test_materialize_bundled_preserves_user_edits(
    pack: Path,
    skill_store: SkillStore,
    tool_store: ToolStore,
    mcp_store: MCPStore,
) -> None:
    """A skill description the user changed survives the next launch."""
    _write_skill(pack / "skills" / "skill-a", description="bundled description")
    await materialize_bundled(
        content_root=pack,
        skill_store=skill_store,
        tool_store=tool_store,
        mcp_store=mcp_store,
    )

    # User edits the description through the Settings UI; the
    # persisted copy under store/skills/<slug>/SKILL.md is what changes.
    await skill_store.update_meta("skill-a", description="user's own description")

    # The bundled content on disk is unchanged (we never write back).
    s2 = await materialize_bundled(
        content_root=pack,
        skill_store=skill_store,
        tool_store=tool_store,
        mcp_store=mcp_store,
    )
    skill = await skill_store.get("skill-a")
    assert skill is not None
    assert skill.description == "user's own description"
    assert s2["skills"]["installed"] == []
    assert len(s2["skills"]["skipped"]) == 1


@pytest.mark.asyncio
async def test_materialize_bundled_partial_domains(
    pack: Path,
    skill_store: SkillStore,
    tool_store: ToolStore,
    mcp_store: MCPStore,
) -> None:
    """Missing domains (e.g. no mcp/ subdir) are simply absent — not an error."""
    _write_skill(pack / "skills" / "skill-a")
    # No tools/, no mcp/.

    summary = await materialize_bundled(
        content_root=pack,
        skill_store=skill_store,
        tool_store=tool_store,
        mcp_store=mcp_store,
    )
    assert len(summary["skills"]["installed"]) == 1
    assert summary["tools"] == {"installed": [], "skipped": [], "errors": []}
    assert summary["mcp"] == {"installed": [], "skipped": [], "errors": []}
