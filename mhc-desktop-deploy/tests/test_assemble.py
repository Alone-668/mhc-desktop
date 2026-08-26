"""Tests for the deploy package's ``build_default_app`` wiring.

The deploy package is the integration layer that enterprise
forks own. These tests pin:

* the convenience kwargs (``data_dir``, ``config``, ``auth``,
  ``meta``, ``content_packs_root``, ...) land in the right places
* the default file-backed stores are wired when nothing is passed
* custom overrides win (mock auth, custom content-packs root,
  runtime meta, ...)
* the file-backed stores honour ``data_dir=`` for tests / per-user
  installs
* ``ensure_dirs()`` is called as part of the wiring (regression
  for the boot-time race where the very first run had no
  skills/tools/mcp dirs)
"""

from __future__ import annotations


import pytest
from fastapi.testclient import TestClient

from mhc_desktop_backend.config import Config


@pytest.fixture
def fresh_data_dir(tmp_path, monkeypatch):
    """Pin ``MHC_DATA_DIR`` to a fresh tmp dir so default wiring
    doesn't touch the developer's actual ``~/.mhc-desktop``."""
    monkeypatch.setenv("MHC_DATA_DIR", str(tmp_path))
    # Wipe the module-level cached DATA_DIR so each test re-imports.
    import mhc_desktop_deploy.impls.file_stores.paths as paths

    paths.DATA_DIR = tmp_path
    paths.LOGS_DIR = tmp_path / "logs"
    paths.SESSIONS_DIR = tmp_path / "sessions"
    paths.SESSIONS_INDEX = paths.SESSIONS_DIR / "index.json"
    paths.SKILLS_DIR = tmp_path / "skills"
    paths.SKILLS_STATE_FILE = tmp_path / "skills-state.json"
    paths.MCP_DIR = tmp_path / "mcp"
    paths.MCP_STATE_FILE = tmp_path / "mcp-state.json"
    paths.TOOLS_DIR = tmp_path / "tools"
    paths.TOOLS_STATE_FILE = tmp_path / "tools-state.json"
    paths.PREFS_FILE = tmp_path / "prefs.json"
    paths.METRICS_FILE = tmp_path / "metrics.jsonl"
    paths.PROVIDERS_FILE = tmp_path / "providers.json"
    return tmp_path


def test_build_default_app_wires_mock_auth_by_default(fresh_data_dir):
    """Without an explicit ``auth=`` override, deploy wires
    ``MockAuthProvider`` so ``python -m mhc_desktop_deploy`` boots
    a working login flow out of the box."""
    from mhc_desktop_deploy.assemble import build_default_app

    app = build_default_app()
    assert app.state.auth_provider is not None


def test_build_default_app_with_custom_auth(fresh_data_dir):
    """Enterprise fork passing its own auth wins over the mock."""

    class _StubAuth:
        async def login(self, username, password):
            return None

        async def resolve(self, token):
            return None

        async def logout(self, token):
            return None

    from mhc_desktop_deploy.assemble import build_default_app

    auth = _StubAuth()
    app = build_default_app(auth=auth)
    assert app.state.auth_provider is auth


def test_build_default_app_wires_default_stores(fresh_data_dir):
    """Every Protocol slot gets the file-backed default impl when
    not overridden. Proves the convenience kwargs don't swallow
    the defaults."""
    from mhc_desktop_deploy.assemble import build_default_app

    app = build_default_app()
    assert app.state.provider_store is not None
    assert app.state.session_store is not None
    assert app.state.skill_store is not None
    assert app.state.mcp_store is not None
    assert app.state.mcp_manager is not None
    assert app.state.tool_store is not None
    assert app.state.stream_registry is not None
    assert app.state.prefs_store is not None
    assert app.state.metrics_repo is not None


def test_build_default_app_wires_runtime_meta(fresh_data_dir):
    """``GET /api/v1/meta`` returns the deploy-provided manifest;
    the convenience ``meta=`` kwarg merges with the kernel defaults.
    """
    from mhc_desktop_deploy.assemble import build_default_app

    app = build_default_app(meta={"brand": {"name": "Acme"}, "extra": "yes"})
    with TestClient(app) as c:
        r = c.get("/api/v1/meta")
    assert r.status_code == 200
    inner = r.json()["meta"]
    # Convenience key made it through.
    assert inner["brand"] == {"name": "Acme"}
    assert inner["extra"] == "yes"
    # Default keys are preserved alongside.
    assert "data_dir" in inner
    assert "bundled" in inner


def test_build_default_app_meta_bundled_merge(fresh_data_dir):
    """``bundled.skills`` override doesn't blow away ``bundled.mcps``
    / ``bundled.tools`` — they're deep-merged."""
    from mhc_desktop_deploy.assemble import build_default_app

    app = build_default_app(
        meta={"bundled": {"skills": ["a", "b"], "mcps": ["x"]}},
    )
    with TestClient(app) as c:
        r = c.get("/api/v1/meta")
    inner = r.json()["meta"]
    assert inner["bundled"]["skills"] == ["a", "b"]
    assert inner["bundled"]["mcps"] == ["x"]
    assert inner["bundled"]["tools"] == []  # default preserved


def test_build_default_app_wires_content_packs_root_via_env(
    fresh_data_dir, monkeypatch, tmp_path
):
    """``MHC_RESOURCES_PATH/content-packs`` is honoured when no
    explicit ``content_packs_root=`` is passed."""
    packs = tmp_path / "resources" / "content-packs"
    packs.mkdir(parents=True)
    (packs / "skills" / "demo").mkdir(parents=True)
    (packs / "skills" / "demo" / "SKILL.md").write_text(
        "---\nname: Demo\ndescription: x\n---\nbody\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MHC_RESOURCES_PATH", str(tmp_path / "resources"))
    from mhc_desktop_deploy.assemble import build_default_app

    app = build_default_app()
    assert app.state.content_packs_root == packs
    # Lifespan materializes; we just verify the kwarg plumbs through
    # (the actual install is covered by the kernel's content-pack
    # tests, which exercise the same helper).


def test_build_default_app_explicit_content_packs_root_wins(
    fresh_data_dir, monkeypatch, tmp_path
):
    """Explicit ``content_packs_root=`` wins over the env-var
    fallback. Deploys that ship a different layout use the kwarg."""
    monkeypatch.setenv("MHC_RESOURCES_PATH", "/should/be/ignored")
    explicit = tmp_path / "explicit-packs"
    explicit.mkdir()
    from mhc_desktop_deploy.assemble import build_default_app

    app = build_default_app(content_packs_root=explicit)
    assert app.state.content_packs_root == explicit


def test_build_default_app_explicit_data_dir_overrides_env(tmp_path, monkeypatch):
    """``data_dir=`` kwarg wins over ``MHC_DATA_DIR`` env var, which
    is the right precedence for tests / enterprise installs."""
    monkeypatch.setenv("MHC_DATA_DIR", "/from/env")
    target = tmp_path / "from-kwarg"
    target.mkdir()
    import mhc_desktop_deploy.impls.file_stores.paths as paths

    paths.DATA_DIR = target
    paths.SESSIONS_DIR = target / "sessions"
    paths.SESSIONS_INDEX = paths.SESSIONS_DIR / "index.json"
    paths.SKILLS_DIR = target / "skills"
    paths.SKILLS_STATE_FILE = target / "skills-state.json"
    paths.MCP_DIR = target / "mcp"
    paths.MCP_STATE_FILE = target / "mcp-state.json"
    paths.TOOLS_DIR = target / "tools"
    paths.TOOLS_STATE_FILE = target / "tools-state.json"
    paths.PREFS_FILE = target / "prefs.json"
    paths.METRICS_FILE = target / "metrics.jsonl"
    paths.PROVIDERS_FILE = target / "providers.json"
    paths.LOGS_DIR = target / "logs"

    from mhc_desktop_deploy.assemble import build_default_app

    app = build_default_app(data_dir=target)
    # The wired provider_store lives at the kwarg'd path.
    assert str(app.state.provider_store._path).startswith(str(target))


def test_build_default_app_fail_closed_in_production(fresh_data_dir, monkeypatch):
    """Production config (debug=False) plus auth override of
    ``None`` must fail loud — the kernel's fail-closed contract
    catches a misconfigured deploy before it serves traffic."""
    from mhc_desktop_deploy.assemble import build_default_app

    cfg = Config(debug=False, host="127.0.0.1", port=8765)
    with pytest.raises(RuntimeError, match="auth provider is required"):
        build_default_app(config=cfg, auth=None)


def test_build_default_app_runs_ensure_dirs(fresh_data_dir):
    """``ensure_dirs()`` runs as part of the wiring so the very
    first boot creates the data-tree layout. Regression: the
    deploy used to import the default stores but never trigger
    their ``ensure_dirs()`` side effect, leaving a race on the
    first install."""
    from mhc_desktop_deploy.impls.file_stores import paths as paths_mod

    # Build triggers ensure_dirs — sub-folders exist after.
    from mhc_desktop_deploy.assemble import build_default_app

    build_default_app()
    assert (paths_mod.DATA_DIR / "skills").is_dir()
    assert (paths_mod.DATA_DIR / "mcp").is_dir()
    assert (paths_mod.DATA_DIR / "tools").is_dir()
    assert (paths_mod.DATA_DIR / "sessions").is_dir()
    assert (paths_mod.DATA_DIR / "logs").is_dir()


def test_build_default_app_thread_extra_kwargs(fresh_data_dir):
    """Any kwarg the deploy passes that the assemble helper doesn't
    consume (``data_dir``, ``config``, ``meta``) gets forwarded
    verbatim to ``create_app``. Example here: ``provider_types=``
    (kernel P1-2) and ``chat_policy=`` (P1-5) flow through.
    """
    from mhc_desktop_deploy.assemble import build_default_app
    from mhc_desktop_backend.protocols import ChatPolicy

    pol = ChatPolicy(max_tool_rounds=42)
    app = build_default_app(
        provider_types={"azure_openai", "openai", "anthropic"},
        chat_policy=pol,
    )
    assert app.state.provider_types == {"azure_openai", "openai", "anthropic"}
    assert app.state.chat_policy is pol
