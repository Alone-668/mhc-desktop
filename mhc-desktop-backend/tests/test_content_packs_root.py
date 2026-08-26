"""Tests for the ``content_packs_root=`` injection point.

The boot-time materialisation of bundled content packs now reads
from ``app.state.content_packs_root`` (set by ``create_app``).
The legacy ``MHC_RESOURCES_PATH`` env var still works as a
back-compat fallback, but the deploy-friendly path is the
explicit kwarg.

These tests cover:

* explicit ``content_packs_root=`` is honoured
* back-compat: ``MHC_RESOURCES_PATH`` env var still triggers
  materialization when no kwarg is passed
* default (no env, no kwarg) means no materialization
* the path may be a sub-tree of any shape; the helper just walks
  ``{skills,tools,mcp}/`` underneath
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mhc_desktop_backend.app import create_app


def tmp_path_for_store() -> Path:
    """Return a fresh tempdir for ``tool_store._dir``.

    The bulk installer writes ``tool.py`` into the store's on-disk
    mirror so it survives backend restarts. We give the in-memory
    test stub a temp dir so the write succeeds without polluting
    the rest of the test workspace.
    """
    import tempfile

    p = Path(tempfile.mkdtemp(prefix="mhc-tool-store-"))
    return p


class _InMemorySkillStore:
    def __init__(self) -> None:
        self.installed: dict[str, dict] = {}

    async def list(self):
        return list(self.installed.values())

    async def get(self, slug):
        return self.installed.get(slug)

    async def get_body(self, slug):
        return None

    async def get_file(self, slug, rel):
        raise FileNotFoundError(rel)

    async def install_from_folder(self, source, *, overwrite=False, origin="imported"):
        slug = source.name
        if slug in self.installed and not overwrite:
            raise RuntimeError(f"already exists: {slug}")
        rec = {"slug": slug, "source": str(source)}
        self.installed[slug] = rec
        # The content-pack helper accesses ``.slug`` on the return
        # value; surface it via the dict's get via a tiny adapter.
        return _DictSkillAdapter(rec)

    async def delete(self, slug):
        self.installed.pop(slug, None)

    async def set_enabled(self, slug, enabled):
        return self.installed[slug]

    async def update_meta(self, slug, *, description=None, body=None):
        return self.installed[slug]

    async def export(self, slug):
        return b""

    async def import_zip(self, data, *, origin="imported"):
        return None

    async def close(self):
        return None


class _DictSkillAdapter:
    """Minimal stand-in for :class:`Skill` that exposes ``.slug``
    attribute access for the content-pack helper. The helper only
    reads ``.slug`` on the return value of ``install_from_folder``,
    so a tiny shim is enough.
    """

    def __init__(self, rec: dict) -> None:
        self._rec = rec
        self.slug = rec["slug"]


class _DictToolAdapter:
    """Same idea as :class:`_DictSkillAdapter` for tools."""

    def __init__(self, rec: dict) -> None:
        self._rec = rec
        self.slug = rec.get("slug", "")


class _InMemoryToolStore:
    def __init__(self) -> None:
        self.installed: dict[str, dict] = {}
        # The bulk-installer persists the source into
        # ``store._dir / slug``. Tests don't need a real fs; we
        # accept the writes into a tmp dir so the call doesn't
        # raise ``AttributeError``.
        self._dir = tmp_path_for_store()

    async def list(self):
        return list(self.installed.values())

    async def get(self, slug):
        return self.installed.get(slug)

    async def get_by_model_name(self, name):
        return None

    async def get_callable(self, slug):
        return None

    async def create(self, data):
        slug = data.get("slug", "")
        self.installed[slug] = data
        return _DictToolAdapter(data)

    async def update(self, slug, data):
        merged = {**self.installed.get(slug, {}), **data}
        self.installed[slug] = merged
        return _DictToolAdapter(merged)

    async def delete(self, slug):
        self.installed.pop(slug, None)

    async def set_enabled(self, slug, enabled):
        return self.installed[slug]

    async def close(self):
        return None


class _InMemoryMCPStore:
    def __init__(self) -> None:
        self.installed: dict[str, dict] = {}

    async def list(self):
        return list(self.installed.values())

    async def get(self, slug):
        return self.installed.get(slug)

    async def upsert(
        self,
        *,
        slug,
        name,
        description,
        command,
        args,
        env=None,
        origin="imported",
    ):
        if slug in self.installed:
            raise RuntimeError("exists")
        rec = {
            "slug": slug,
            "name": name,
            "description": description,
            "command": command,
            "args": args,
            "env": env or {},
        }
        self.installed[slug] = rec
        return _DictMCPAdapter(rec)

    async def delete(self, slug):
        self.installed.pop(slug, None)

    async def set_enabled(self, slug, enabled):
        return self.installed[slug]

    async def record_discovery(self, slug, tools, *, error=""):
        return None

    async def close(self):
        return None


class _DictMCPAdapter:
    """Same idea for MCP servers."""

    def __init__(self, rec: dict) -> None:
        self._rec = rec
        self.slug = rec["slug"]


def _write_skill(root: Path, slug: str, name: str) -> None:
    folder = root / "skills" / slug
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: from pack\n---\n\nbody\n",
        encoding="utf-8",
    )


def _write_tool(root: Path, slug: str) -> None:
    folder = root / "tools" / slug
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "tool.py").write_text(
        "async def tool_run():\n    return 'hi'\n", encoding="utf-8"
    )
    (folder / "manifest.json").write_text(
        json.dumps({"name": slug, "description": "from pack"}),
        encoding="utf-8",
    )


def _write_mcp(root: Path, slug: str, command: str) -> None:
    folder = root / "mcp" / slug
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "config.json").write_text(
        json.dumps({"name": slug, "command": command, "args": []}),
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_create_app_with_content_packs_root(tmp_path: Path):
    """Pass an explicit content-packs root and verify the lifespan
    materialises everything under it."""
    root = tmp_path / "content-packs"
    _write_skill(root, "alpha", "Alpha skill")
    _write_tool(root, "echo-tool")
    _write_mcp(root, "alpha-mcp", "echo")

    skills = _InMemorySkillStore()
    tools = _InMemoryToolStore()
    mcps = _InMemoryMCPStore()

    app = create_app(
        skills=skills,
        tools=tools,
        mcp_store=mcps,
        content_packs_root=root,
    )
    # Drive the lifespan by opening a TestClient context.
    with TestClient(app):
        pass
    # Materialization happens during startup, before yield.
    assert "alpha" in skills.installed
    assert "echo-tool" in tools.installed
    assert "alpha-mcp" in mcps.installed


@pytest.mark.asyncio
async def test_create_app_no_content_packs_root_no_op(tmp_path: Path):
    """Without a root and without ``MHC_RESOURCES_PATH`` in the
    environment, materialization is a no-op (the lifespan skips it
    entirely). Built-in tools (``load_skill``) still register via
    ``ensure_builtin_tools`` — they're kernel-owned, not content
    packs — so the assertion excludes them."""
    import os

    os.environ.pop("MHC_RESOURCES_PATH", None)
    skills = _InMemorySkillStore()
    tools = _InMemoryToolStore()
    mcps = _InMemoryMCPStore()
    app = create_app(skills=skills, tools=tools, mcp_store=mcps)
    with TestClient(app):
        pass
    assert skills.installed == {}
    # Built-in ``load_skill`` always lands in the tool catalog on
    # startup; the test's intent is "no content-pack tools got
    # pulled from disk", so we exclude the built-in.
    content_pack_tools = {
        k: v for k, v in tools.installed.items() if k != "load_skill"
    }
    assert content_pack_tools == {}
    assert mcps.installed == {}


@pytest.mark.asyncio
async def test_create_app_falls_back_to_env_var(tmp_path: Path, monkeypatch):
    """``MHC_RESOURCES_PATH`` still works for deploys that haven't
    been updated to use the explicit kwarg yet. The kernel
    appends ``/content-packs`` to the env var's value."""
    root = tmp_path / "resources" / "content-packs"
    _write_skill(root, "beta", "Beta skill")

    monkeypatch.setenv("MHC_RESOURCES_PATH", str(tmp_path / "resources"))
    skills = _InMemorySkillStore()
    tools = _InMemoryToolStore()
    mcps = _InMemoryMCPStore()
    app = create_app(skills=skills, tools=tools, mcp_store=mcps)
    with TestClient(app):
        pass
    assert "beta" in skills.installed
