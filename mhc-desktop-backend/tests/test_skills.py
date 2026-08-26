"""Smoke tests for the skills subsystem.

Covers:
* frontmatter parse / render roundtrip
* SkillStore: install, list, toggle, update_meta, export, import_zip
* build_skill_prompt: filters disabled, concatenates enabled

These run against an isolated tmp dir so they don't touch the user's
real ``~/.mhc-desktop/skills``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from mhc_desktop_backend.skills import (
    SkillError,
    format_skill_message,
)
from mhc_desktop_backend.skills.frontmatter import (
    FrontmatterError,
    parse_skill_md,
    render_skill_md,
)
from mhc_desktop_backend.skills.models import Skill, slugify
from mhc_desktop_deploy.impls.file_stores.skills_store import SkillStore


# ── Frontmatter ────────────────────────────────────────────────────────────


def test_parse_skill_md_minimal():
    fm, body = parse_skill_md(
        "---\nname: hello\ndescription: a friendly skill\n---\n\n# body\n"
    )
    assert fm.name == "hello"
    assert fm.description == "a friendly skill"
    assert body.startswith("# body")


def test_parse_skill_md_no_frontmatter():
    fm, body = parse_skill_md("# just markdown\nno frontmatter here")
    assert fm.name == ""
    assert body == "# just markdown\nno frontmatter here"


def test_parse_skill_md_invalid_yaml_raises():
    with pytest.raises(FrontmatterError):
        parse_skill_md("---\n- list not mapping\n---\n\nbody")


def test_validate_name_rules():
    from mhc_desktop_backend.skills.frontmatter import SkillFrontmatter

    fm = SkillFrontmatter(name="valid-name", description="ok")
    assert fm.validate() == []
    fm = SkillFrontmatter(name="Bad Name", description="ok")
    assert any("lowercase" in e for e in fm.validate())
    fm = SkillFrontmatter(name="ok", description="x" * 2000)
    assert any("1024" in e for e in fm.validate())


def test_render_skill_md_roundtrip():
    from mhc_desktop_backend.skills.frontmatter import SkillFrontmatter

    fm = SkillFrontmatter(name="x", description="d", version="1.0")
    text = render_skill_md(fm, "## body content\n")
    fm2, body = parse_skill_md(text)
    assert fm2.name == "x"
    assert fm2.description == "d"
    assert fm2.version == "1.0"
    assert body.strip() == "## body content"


def test_slugify():
    assert slugify("Hello World") == "hello-world"
    assert slugify("  spaces   collapse  ") == "spaces-collapse"
    assert slugify("MIXED_case") == "mixed-case"
    assert slugify("---") == "skill"


# ── SkillStore ────────────────────────────────────────────────────────────


def _make_skill(root: Path, *, name: str, desc: str, body: str = "## body") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    p = root / name
    p.mkdir()
    (p / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {desc}\n---\n\n{body}\n",
        encoding="utf-8",
    )
    return p


@pytest.fixture
def skill_store(tmp_path):
    return SkillStore(
        skills_dir=tmp_path / "skills",
        state_file=tmp_path / "skills-state.json",
    )


def test_install_from_folder(skill_store, tmp_path):
    src = _make_skill(tmp_path / "src", name="commit-msg", desc="commit stuff")
    s = asyncio.run(skill_store.install_from_folder(src))
    assert s.slug == "commit-msg"
    assert s.name == "commit-msg"
    assert s.origin == "imported"
    assert s.enabled is True


def test_install_rejects_missing_skill_md(skill_store, tmp_path):
    src = tmp_path / "broken"
    src.mkdir()
    with pytest.raises(SkillError, match="SKILL.md"):
        asyncio.run(skill_store.install_from_folder(src))


def test_install_rejects_invalid_frontmatter(skill_store, tmp_path):
    src = tmp_path / "broken"
    src.mkdir()
    (src / "SKILL.md").write_text("---\n- list, not map\n---\n", encoding="utf-8")
    with pytest.raises(SkillError, match="frontmatter"):
        asyncio.run(skill_store.install_from_folder(src))


def test_install_conflict_without_overwrite(skill_store, tmp_path):
    src = _make_skill(tmp_path / "src", name="dup", desc="first")
    asyncio.run(skill_store.install_from_folder(src))
    with pytest.raises(SkillError, match="already exists"):
        asyncio.run(skill_store.install_from_folder(src))
    # overwrite=True succeeds
    s2 = asyncio.run(skill_store.install_from_folder(src, overwrite=True))
    assert s2.slug == "dup"


def test_set_enabled_persists(skill_store, tmp_path):
    src = _make_skill(tmp_path / "src", name="tog", desc="d")
    asyncio.run(skill_store.install_from_folder(src))
    asyncio.run(skill_store.set_enabled("tog", False))
    s = asyncio.run(skill_store.get("tog"))
    assert s.enabled is False


def test_update_meta_writes_frontmatter(skill_store, tmp_path):
    src = _make_skill(tmp_path / "src", name="ed", desc="old desc", body="## old")
    asyncio.run(skill_store.install_from_folder(src))
    asyncio.run(
        skill_store.update_meta("ed", description="new desc", body="## new body")
    )
    s = asyncio.run(skill_store.get("ed"))
    assert s.description == "new desc"
    assert s.body == "## new body\n"


def test_export_then_import_zip_roundtrip(skill_store, tmp_path):
    src = _make_skill(
        tmp_path / "src",
        name="roundtrip",
        desc="",
        body="## roundtrip body\n",
    )
    asyncio.run(skill_store.install_from_folder(src))
    blob = asyncio.run(skill_store.export("roundtrip"))
    assert len(blob) > 50  # not empty
    asyncio.run(skill_store.delete("roundtrip"))
    assert asyncio.run(skill_store.get("roundtrip")) is None
    s = asyncio.run(skill_store.import_zip(blob))
    assert s.slug == "roundtrip"


def test_get_file_blocks_traversal(skill_store, tmp_path):
    src = _make_skill(tmp_path / "src", name="safe", desc="d")
    asyncio.run(skill_store.install_from_folder(src))
    with pytest.raises(SkillError, match="escape"):
        asyncio.run(skill_store.get_file("safe", "../../etc/passwd"))


def test_delete_removes_dir_and_state(skill_store, tmp_path):
    src = _make_skill(tmp_path / "src", name="rm", desc="d")
    asyncio.run(skill_store.install_from_folder(src))
    assert (skill_store._dir / "rm").is_dir()
    asyncio.run(skill_store.delete("rm"))
    assert not (skill_store._dir / "rm").exists()


# ── format_skill_message ──────────────────────────────────────────────────────────────


def test_format_skill_message_includes_description_body_files():
    """The user-role message body for a skill must carry the
    description, the body, and a listing of attached files — the
    three things the model needs to know about an attached skill."""
    s = Skill(
        slug="x",
        name="x",
        description="Use when reviewing code.",
        body="Body text",
        files=["scripts/template.md", "data/seeds.json"],
    )
    out = format_skill_message(s)
    assert "[Attached skill: x" in out, "skill not labeled as attached"
    assert "Use when reviewing code." in out, "description not injected"
    assert "Body text" in out, "body not injected"
    assert "`scripts/template.md`" in out, "file listing missing"
    assert "`data/seeds.json`" in out
    assert "Apply this skill" in out, "closing directive missing"


def test_format_skill_message_handles_missing_optional_fields():
    s = Skill(slug="y", name="y", description="")  # empty desc, no body, no files
    out = format_skill_message(s)
    assert "[Attached skill: y" in out
    assert "(skill has no body)" in out


# ── _inline_skill_files ────────────────────────────────────────────────────────────────────────────────


def test_inline_skill_files_appends_contents(tmp_path):
    """Each non-SKILL.md file should be inlined into the skill body as
    a fenced code block, so the model can read templates / scripts
    / datasets that ship with the skill."""
    from mhc_desktop_backend.api.chat import _inline_skill_files

    # Build a real skill store + skill with one attached file.
    store = SkillStore(skills_dir=tmp_path / "s", state_file=tmp_path / "st.json")
    skill_dir = tmp_path / "src"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: demo\ndescription: d\n---\n\n## body\n",
        encoding="utf-8",
    )
    (skill_dir / "scripts").mkdir()
    (skill_dir / "scripts" / "tpl.md").write_text(
        "# template\n\nUse this skeleton\n",
        encoding="utf-8",
    )

    skill = asyncio.run(store.install_from_folder(skill_dir))
    inlined = asyncio.run(_inline_skill_files(skill, store))
    assert "Use this skeleton" in inlined.body
    assert "```md" in inlined.body
    assert "### `scripts/tpl.md`" in inlined.body


def test_inline_skill_files_skips_oversize(tmp_path):
    """Files larger than the per-file cap should be listed but not
    inlined, so a misbehaving skill can't OOM the request."""
    from mhc_desktop_backend.api.chat import _inline_skill_files
    from mhc_desktop_backend.protocols import ChatPolicy

    cap = ChatPolicy().inline_file_max_bytes
    store = SkillStore(skills_dir=tmp_path / "s", state_file=tmp_path / "st.json")
    skill_dir = tmp_path / "src"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: big\ndescription: d\n---\n\nbody\n",
        encoding="utf-8",
    )
    big = skill_dir / "huge.md"
    big.write_bytes(b"X" * (cap + 100))

    skill = asyncio.run(store.install_from_folder(skill_dir))
    inlined = asyncio.run(_inline_skill_files(skill, store))
    assert "XX" * 100 not in inlined.body  # not inlined
    assert "exceeds" in inlined.body.lower()  # placeholder shown


# ── _resolve_skill_messages ───────────────────────────────────────────────────────────


def test_resolve_skill_messages_filters_disabled(tmp_path):
    from mhc_desktop_backend.api.chat import _resolve_skill_messages

    store = SkillStore(skills_dir=tmp_path / "s", state_file=tmp_path / "st.json")
    enabled = tmp_path / "enabled"
    enabled.mkdir()
    (enabled / "SKILL.md").write_text(
        "---\nname: enabled\ndescription: d\n---\n\nbody-on\n",
        encoding="utf-8",
    )
    disabled = tmp_path / "disabled"
    disabled.mkdir()
    (disabled / "SKILL.md").write_text(
        "---\nname: disabled\ndescription: d\n---\n\nbody-off\n",
        encoding="utf-8",
    )
    asyncio.run(store.install_from_folder(enabled))
    asyncio.run(store.install_from_folder(disabled))
    asyncio.run(store.set_enabled("disabled", False))

    msgs = asyncio.run(_resolve_skill_messages(["enabled", "disabled"], store))
    assert len(msgs) == 1
    assert msgs[0]["role"] == "user"
    assert "body-on" in msgs[0]["content"]
    assert "body-off" not in msgs[0]["content"]


def test_resolve_skill_messages_unknown_raises(tmp_path):
    from mhc_desktop_backend.api.chat import _resolve_skill_messages

    store = SkillStore(skills_dir=tmp_path / "s", state_file=tmp_path / "st.json")
    with pytest.raises(SkillError, match="not found"):
        asyncio.run(_resolve_skill_messages(["nope"], store))


def test_skills_spliced_before_user_input(tmp_path):
    """Simulate the chat endpoint's message assembly: prior history
    + skill messages + current user input must come out in that
    order so the model sees the \"attached skill\" block right before
    the user's actual question."""
    from mhc_desktop_backend.api.chat import _resolve_skill_messages

    store = SkillStore(skills_dir=tmp_path / "s", state_file=tmp_path / "st.json")
    for slug in ("a", "b"):
        d = tmp_path / slug
        d.mkdir()
        (d / "SKILL.md").write_text(
            f"---\nname: {slug}\ndescription: d-{slug}\n---\n\nbody-{slug}\n",
            encoding="utf-8",
        )
        asyncio.run(store.install_from_folder(d))

    history = [
        {"role": "user", "content": "earlier"},
        {"role": "assistant", "content": "earlier reply"},
        {"role": "user", "content": "current input"},
    ]
    skill_messages = asyncio.run(_resolve_skill_messages(["a", "b"], store))
    assert len(skill_messages) == 2
    # Splice: history[:-1] + skill_messages + history[-1]
    assembled = [*history[:-1], *skill_messages, history[-1]]
    roles = [m["role"] for m in assembled]
    assert roles == [
        "user",
        "assistant",
        "user",  # skill a
        "user",  # skill b
        "user",  # current input
    ]
    # Skill messages come BEFORE the current input
    assert "body-a" in skill_messages[0]["content"]
    assert "body-b" in skill_messages[1]["content"]
    assert assembled[-1]["content"] == "current input"
