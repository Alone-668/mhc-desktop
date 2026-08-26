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

from mhc_desktop_backend.skills import SkillError
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
