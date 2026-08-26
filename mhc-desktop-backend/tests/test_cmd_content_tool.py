"""The cmd content-pack tool must keep working as distributed.

Loads the real tool.py from content-packs and exercises the same
contract the chat layer relies on: semantic error prefixes, exit
markers, timeout kill, and no orphan processes. Skips gracefully on
non-Windows hosts (the tool itself yields [error:env] there).
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest

TOOL_PATH = (
    Path(__file__).resolve().parents[2]
    / "mhc-desktop-app"
    / "content-packs"
    / "tools"
    / "cmd"
    / "tool.py"
)

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="cmd tool is Windows-only"
)


@pytest.fixture(scope="module")
def cmd_tool():
    spec = importlib.util.spec_from_file_location("cmd_content_tool", TOOL_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


async def collect(coro) -> list[str]:
    out: list[str] = []
    async for chunk in coro:
        out.append(chunk)
    return out


@pytest.mark.asyncio
async def test_cmd_clean_success(cmd_tool):
    out = await collect(cmd_tool.tool_run(command="echo Hello World", timeout=10))
    assert out == ["Hello World\r\n"]


@pytest.mark.asyncio
async def test_cmd_nonzero_exit_marker(cmd_tool):
    out = await collect(cmd_tool.tool_run(command="exit /b 7", timeout=10))
    assert out == ["[exit 7]\n"]


@pytest.mark.asyncio
async def test_cmd_stderr_captured(cmd_tool):
    out = await collect(cmd_tool.tool_run(command="echo oops 1>&2", timeout=10))
    assert any("oops" in c for c in out)
    assert any(c.startswith("[stderr]") for c in out)


@pytest.mark.asyncio
async def test_cmd_bad_args_semantic(cmd_tool):
    out = await collect(cmd_tool.tool_run(command="", timeout=10))
    assert out[0].startswith("[error:bad-arg]")
    out = await collect(cmd_tool.tool_run(command="echo hi", timeout=0))
    assert out[0].startswith("[error:bad-arg]")
    out = await collect(cmd_tool.tool_run(command="echo hi", timeout=True))
    assert out[0].startswith("[error:bad-arg]")


@pytest.mark.asyncio
async def test_cmd_timeout_kills_process_tree(cmd_tool):
    """The timeout must terminate the child AND its subprocesses
    (ping), returning promptly instead of waiting for the command to
    finish on its own."""
    import time

    t0 = time.time()
    out = await collect(
        cmd_tool.tool_run(command="ping -n 60 127.0.0.1 >nul", timeout=2)
    )
    elapsed = time.time() - t0
    assert elapsed < 15, f"timeout took {elapsed:.1f}s — process tree not killed"
    assert out == ["[timeout] cmd did not finish within 2s; killed\n"]


@pytest.mark.asyncio
async def test_cmd_cancel_leaves_no_orphan(cmd_tool):
    """Cancelling the consuming task must propagate CancelledError
    and kill the child tree (no orphan ping processes)."""
    import subprocess

    async def consume() -> list[str]:
        return await collect(
            cmd_tool.tool_run(command="ping -n 60 127.0.0.1 >nul", timeout=60)
        )

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.8)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    # Give cleanup a moment, then assert no ping/cmd spawned by us
    # is still alive. We can't easily scope by parent, so just check
    # the count didn't grow — ping is short-lived anyway; a leftover
    # from a failed kill would still be running here.
    await asyncio.sleep(1.0)
    r = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq ping.exe"],
        capture_output=True,
        text=True,
    )
    # "INFO: No tasks are running" → no ping lines
    assert "ping.exe" not in r.stdout or "No tasks" in r.stdout
