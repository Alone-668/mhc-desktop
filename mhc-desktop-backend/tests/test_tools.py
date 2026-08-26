"""Tests for the Tools subsystem — parallels test_skills.py.

We exercise the same surface the API router exposes so we know the
full CRUD path works end-to-end before the frontend gets a chance
to depend on it. The installer ships zero bundled tools; customers
provide their own through bulk import.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from mhc_desktop_backend.api.tools import router as tools_router
from mhc_desktop_deploy.impls.file_stores.tools_store import ToolStore
from mhc_desktop_backend.tools.imports import (
    DEFAULT_TOOL_TIMEOUT_SECONDS,
    run_tool,
)


@pytest.fixture
def fresh_store(tmp_path: Path) -> ToolStore:
    store = ToolStore(tools_dir=tmp_path)
    return store


# ── CRUD ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_local_tool(fresh_store: ToolStore):
    tool = await fresh_store.create(
        {
            "slug": "echo",
            "name": "Echo",
            "description": "Echoes input back as text",
            "kind": "local",
            "parameters": {"type": "object", "properties": {"x": {"type": "string"}}},
        }
    )
    assert tool.slug == "echo"
    assert tool.origin == "imported"
    tools = await fresh_store.list()
    assert any(t.slug == "echo" for t in tools)


@pytest.mark.asyncio
async def test_create_duplicate_slug_rejected(fresh_store: ToolStore):
    await fresh_store.create({"slug": "echo", "name": "Echo"})
    with pytest.raises(Exception):
        await fresh_store.create({"slug": "echo", "name": "Echo 2"})


@pytest.mark.asyncio
async def test_set_enabled(fresh_store: ToolStore):
    await fresh_store.create({"slug": "echo", "name": "Echo"})
    updated = await fresh_store.set_enabled("echo", False)
    assert updated.enabled is False
    fetched = await fresh_store.get("echo")
    assert fetched is not None and fetched.enabled is False


@pytest.mark.asyncio
async def test_delete_drops_state(fresh_store: ToolStore):
    await fresh_store.create({"slug": "echo", "name": "Echo"})
    await fresh_store.delete("echo")
    assert await fresh_store.get("echo") is None


@pytest.mark.asyncio
async def test_update_replaces_fields(fresh_store: ToolStore):
    await fresh_store.create({"slug": "echo", "name": "Echo", "description": "old"})
    updated = await fresh_store.update(
        "echo", {"description": "new", "kind": "remote", "endpoint_url": "http://x"}
    )
    assert updated.description == "new"
    assert updated.kind == "remote"
    assert updated.endpoint_url == "http://x"


# ── run_tool contract ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_tool_timeout_cancels():
    """If a tool exceeds the timeout, run_tool should raise rather
    than blocking forever. The 15-minute default keeps the goal's
    ceiling intact for production, but the test uses a sub-second
    timeout so we don't actually wait."""

    async def slow(**_: dict) -> str:
        await asyncio.sleep(60)
        return "should not see this"

    with pytest.raises(asyncio.TimeoutError):
        async for _ in run_tool(slow, {}, timeout=0.1):
            pass


@pytest.mark.asyncio
async def test_run_tool_cancel_event_interrupts():
    """The cancel_event must interrupt a tool call that's still
    running. Mirrors how the chat handler's per-session cancel
    flag propagates."""

    cancel = asyncio.Event()

    async def slow(**_: dict) -> str:
        await asyncio.sleep(60)
        return "should not see this"

    async def trigger_cancel():
        await asyncio.sleep(0.05)
        cancel.set()

    asyncio.create_task(trigger_cancel())
    with pytest.raises(asyncio.CancelledError):
        async for _ in run_tool(
            slow, {}, timeout=DEFAULT_TOOL_TIMEOUT_SECONDS, cancel_event=cancel
        ):
            pass


@pytest.mark.asyncio
async def test_run_tool_with_single_return_value():
    """Tools that return a single value (not an async iterator)
    still produce one chunk."""

    async def one(**kwargs: dict) -> str:
        return f"got {kwargs.get('x', '?')}"

    out: list[str] = []
    async for c in run_tool(one, {"x": "hello"}):
        out.append(c)
    assert out == ["got hello"]


# ── import + execute round-trip ─────────────────────────────────────


@pytest.mark.asyncio
async def test_import_local_tool_and_execute(tmp_path: Path):
    """End-to-end: import-source flow + execute via the same store.

    This is the path the chat handler will take — the front end
    posts ``source=`` to ``/api/v1/tools/import-source``, the
    backend compiles and caches the callable, then a chat call
    later in the same process pulls the cached callable.
    """
    from mhc_desktop_backend.tools.imports import import_local_tool

    source = """
async def tool_run(name: str = "world") -> str:
    return f"hello {name}"
"""
    fn = await import_local_tool("greet", source)
    assert callable(fn)
    out: list[str] = []
    async for c in run_tool(fn, {"name": "peter"}):
        out.append(c)
    assert out == ["hello peter"]


@pytest.mark.asyncio
async def test_import_syntax_error_raises_clear():
    from mhc_desktop_backend.tools.imports import import_local_tool

    with pytest.raises(ValueError, match="syntax error"):
        await import_local_tool("bad", "def tool_run(:\n  pass\n")


@pytest.mark.asyncio
async def test_import_missing_entrypoint_raises_clear():
    from mhc_desktop_backend.tools.imports import import_local_tool

    with pytest.raises(ValueError, match="no callable"):
        await import_local_tool("missing", "x = 1\n")


# ── API router ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_api_create_get_update_delete(tmp_path: Path):
    app = FastAPI()
    app.state.tool_store = ToolStore(tools_dir=tmp_path)
    app.include_router(tools_router)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.post(
            "/api/v1/tools",
            json={
                "slug": "demo",
                "name": "Demo",
                "description": "d",
                "kind": "local",
                "parameters": {"type": "object", "properties": {}},
            },
        )
        assert r.status_code == 201
        assert r.json()["slug"] == "demo"

        r = await client.get("/api/v1/tools/demo")
        assert r.status_code == 200

        r = await client.put(
            "/api/v1/tools/demo/enabled",
            json={"enabled": False},
        )
        assert r.status_code == 200
        assert r.json()["enabled"] is False

        r = await client.delete("/api/v1/tools/demo")
        assert r.status_code == 204

        r = await client.get("/api/v1/tools/demo")
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_api_import_source_round_trip(tmp_path: Path):
    app = FastAPI()
    app.state.tool_store = ToolStore(tools_dir=tmp_path)
    app.include_router(tools_router)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.post(
            "/api/v1/tools/import-source",
            json={
                "slug": "greeter",
                "name": "Greeter",
                "description": "Greets the world",
                "source": "async def tool_run(name: str = 'world'):\n    return f'hello {name}'\n",
            },
        )
        assert r.status_code == 201, r.text
        assert r.json()["slug"] == "greeter"


@pytest.mark.asyncio
async def test_api_create_then_export_returns_manifest(tmp_path: Path):
    app = FastAPI()
    app.state.tool_store = ToolStore(tools_dir=tmp_path)
    app.include_router(tools_router)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # Create a user tool first; the bundled `now` tool no longer
        # ships with the installer.
        r = await client.post(
            "/api/v1/tools",
            json={
                "slug": "demo",
                "name": "Demo",
                "description": "d",
                "kind": "local",
                "parameters": {"type": "object", "properties": {}},
            },
        )
        assert r.status_code == 201
        r = await client.get("/api/v1/tools/demo/export")
        assert r.status_code == 200
        data = r.json()
        assert data["schema"] == "mhc-tool.v1"
        assert data["slug"] == "demo"
        assert data["kind"] == "local"


@pytest.mark.asyncio
async def test_import_persists_source_and_survives_restart(tmp_path: Path):
    """The tool source must be copied to the data dir at import time
    and lazily re-imported on a cache miss (backend restart / uvicorn
    reload wipes the process-local callable cache). Without this a
    tool imported in one session becomes "no callable registered" in
    the next — the exact bug reported by the customer.
    """
    from mhc_desktop_backend.tools.imports import (
        evict_cached_local,
        import_tool_from_disk,
    )
    from mhc_desktop_deploy.impls.file_stores.tools_store import ToolStore

    store = ToolStore(tools_dir=tmp_path)
    source = (
        "async def tool_run(name: str = 'world') -> str:\n    return f'hello {name}'\n"
    )

    # Import via the API path (import-source), which must persist the
    # source to disk.
    app = FastAPI()
    app.state.tool_store = store
    app.include_router(tools_router)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.post(
            "/api/v1/tools/import-source",
            json={"slug": "persist-me", "source": source},
        )
        assert r.status_code == 201, r.text

    # The on-disk copy must exist.
    disk_copy = tmp_path / "persist-me" / "tool.py"
    assert disk_copy.is_file(), "import-source did not persist tool.py"
    assert disk_copy.read_text("utf-8") == source

    # The store record's source_path must point at the copy.
    tool = await store.get("persist-me")
    assert tool is not None
    assert Path(tool.source_path) == disk_copy

    # Simulate a backend restart: the process-local cache is empty
    # (evict it), then a chat call resolves the callable — it should
    # lazily re-import from disk instead of returning None.
    evict_cached_local("persist-me")
    from mhc_desktop_backend.tools.imports import get_cached_local

    assert get_cached_local("persist-me") is None

    fn = await import_tool_from_disk("persist-me", tool.source_path)
    assert fn is not None, "lazy re-import from disk returned None"
    out: list[str] = []
    async for c in run_tool(fn, {"name": "restarted"}):
        out.append(c)
    assert out == ["hello restarted"]


@pytest.mark.asyncio
async def test_delete_removes_persisted_source(tmp_path: Path):
    """Deleting a tool must also remove its on-disk source copy so a
    re-import starts clean."""
    from mhc_desktop_deploy.impls.file_stores.tools_store import ToolStore

    store = ToolStore(tools_dir=tmp_path)
    app = FastAPI()
    app.state.tool_store = store
    app.include_router(tools_router)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        r = await client.post(
            "/api/v1/tools/import-source",
            json={
                "slug": "temp-tool",
                "source": "async def tool_run() -> str:\n    return 'x'\n",
            },
        )
        assert r.status_code == 201
        assert (tmp_path / "temp-tool" / "tool.py").is_file()

        r = await client.delete("/api/v1/tools/temp-tool")
        assert r.status_code == 204
        assert not (tmp_path / "temp-tool").exists()
