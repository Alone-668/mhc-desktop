"""The backend must spawn subprocesses (PowerShell tool) in dev mode.

uvicorn on Windows picks SelectorEventLoop when ``reload``/``workers``
is set (its ``use_subprocess`` flag), and SelectorEventLoop on
Windows has no subprocess support — ``asyncio.create_subprocess_exec``
raises NotImplementedError. main.py overrides the loop factory to
always return a ProactorEventLoop; these tests pin that behavior.
"""

from __future__ import annotations

import asyncio
import sys

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="ProactorEventLoop is Windows-only; on POSIX the factory "
    "returns the default selector loop",
)


def test_proactor_loop_factory_returns_proactor_loop() -> None:
    from mhc_desktop_backend.main import _proactor_loop_factory

    loop = _proactor_loop_factory(use_subprocess=True)
    assert isinstance(loop, asyncio.ProactorEventLoop)
    loop.close()


def test_proactor_loop_can_spawn_subprocess() -> None:
    """The whole point: a loop created by our factory must be able
    to spawn a child process (SelectorEventLoop on Windows can't and
    raises NotImplementedError inside create_subprocess_exec)."""
    from mhc_desktop_backend.main import _proactor_loop_factory

    loop = _proactor_loop_factory(use_subprocess=True)

    async def _spawn() -> int:
        proc = await asyncio.create_subprocess_exec(
            "cmd.exe",
            "/c",
            "exit 0",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        return await proc.wait()

    code = loop.run_until_complete(_spawn())
    assert code == 0
    loop.close()
