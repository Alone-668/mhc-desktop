"""Run a Windows cmd.exe command (batch-style).

Two required parameters:

* ``command``  (string)  — the exact command line to run in cmd.exe
* ``timeout``  (int)     — per-call ceiling in seconds, hard cap 600

Execution model:

* Writes the command to a temporary ``.bat`` file (UTF-8-safe: the
  file is encoded to the system OEM/ANSI code page so non-ASCII
  text survives cmd's batch parser) and runs ``cmd.exe /d /c <bat>``
  via ``asyncio.create_subprocess_exec`` — the backend event loop
  stays responsive while the child runs.
* A temp .bat avoids cmd's infamous ``/c "..."`` quoting rules
  entirely: the command is passed as file content, not as an
  argument, so embedded quotes / ``&`` / ``|`` / ``^`` / ``%`` are
  interpreted by cmd exactly as written.
* Streams stdout line-by-line so the LLM sees partial output before
  the process exits. stderr is buffered and appended at the end so
  errors don't get lost in a chatty stdout stream.
* Capped by an internal ``asyncio.wait`` at ``timeout`` seconds.
* Always cleans up: any cancellation (user clicked "stop") or
  timeout kills the child process and deletes the temp .bat before
  we return. The backend's ``run_tool`` wrapper races the runner
  task against a cancel event and will inject ``CancelledError``
  into this function — the ``finally`` block ensures the cmd child
  dies with it.

Hard cap on ``timeout`` is 600 seconds (10 min). The chat layer
already has its own 15-minute safety net above this, so even a
misbehaving timeout argument cannot hang the session.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from typing import Any, AsyncIterator

# Maximum timeout we'll honour from a tool call. Anything higher
# would defeat the purpose — a runaway tool shouldn't survive long
# enough to need it, and longer-lived tasks belong in a script, not
# a chat invocation.
MAX_TIMEOUT_SECONDS = 600

# Default if the manifest supplies one. The model is expected to
# always pass timeout explicitly; this is just the schema default.
DEFAULT_TIMEOUT_SECONDS = 60

# cmd.exe location — ships with every Windows install.
if sys.platform != "win32":
    CMD_EXE = ""
else:
    CMD_EXE = "cmd.exe"


def _encode_bat(text: str) -> bytes:
    """Encode a batch file body so cmd.exe parses non-ASCII correctly.

    cmd's batch parser reads the file using the system OEM code page
    (GBK / cp936 on zh-CN Windows, cp437 on en-US). We encode with
    that code page when it can represent the text, falling back to
    UTF-8 (which cmd reads as best-effort bytes) otherwise. Writing
    the .bat in binary mode avoids Python's text-mode newline
    translation turning ``\\r\\n`` into ``\\r\\r\\n``.
    """
    try:
        return text.encode("gbk")
    except UnicodeEncodeError:
        return text.encode("utf-8")


def _decode_out(data: bytes) -> str:
    """Decode cmd output using the OEM code page, then UTF-8.

    cmd's output uses the console code page, which is the OEM code
    page by default (GBK on zh-CN). On English systems the same
    bytes are cp437/ASCII — GBK decoding of pure-ASCII bytes is
    identical, so trying GBK first is safe there too.
    """
    try:
        return data.decode("gbk")
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="replace")


async def tool_run(
    *, command: str, timeout: int = DEFAULT_TIMEOUT_SECONDS
) -> AsyncIterator[str]:
    """Run ``command`` in cmd.exe and stream stdout.

    Yields decoded lines (newline preserved). The final yield is
    either an empty string (clean exit) or a one-line ``[exit N]``
    marker on non-zero exit. stderr is collected and yielded after
    stdout finishes (so it doesn't interleave with a chatty command).

    Errors are formatted semantically so the model can recover on
    the next call:
      * ``[error:bad-arg]``  — fix the argument and retry
      * ``[error:env]``      — environment issue, do not retry
      * ``[timeout]``        — command ran too long, retry with bigger timeout
      * ``[error]``          — unexpected; message includes exception class
    """

    # ---- argument validation ---------------------------------------
    if not isinstance(command, str):
        yield (
            "[error:bad-arg] command must be a string (got "
            + type(command).__name__
            + ")"
        )
        return
    if not command.strip():
        yield (
            "[error:bad-arg] command must be a non-empty command line. "
            "hint: pass a real command, e.g. 'dir /b' or 'ping -n 2 127.0.0.1'"
        )
        return
    if isinstance(timeout, bool) or not isinstance(timeout, int):
        yield (
            f"[error:bad-arg] timeout must be a positive integer (seconds); got {type(timeout).__name__} {timeout!r}. "
            "hint: omit the field to use the default 60, or pass an int between 1 and 600"
        )
        return
    if timeout <= 0:
        yield (
            f"[error:bad-arg] timeout must be > 0 seconds; got {timeout}. "
            "hint: pick a wall-clock budget appropriate for the command (e.g. 30s for queries, 300s for installs)"
        )
        return
    if timeout > MAX_TIMEOUT_SECONDS:
        # Silently clamp to the ceiling rather than rejecting the
        # call — the model is allowed to ask for "as long as
        # possible" and we honour that with the documented cap.
        timeout = MAX_TIMEOUT_SECONDS

    if sys.platform != "win32":
        yield (
            f"[error:env] cmd tool only runs on Windows (this host is {sys.platform}). "
            "hint: this is a host limitation — calling cmd on Linux/macOS will always fail"
        )
        return

    # ---- write the temp .bat ---------------------------------------
    # @echo off: don't echo each command line back into stdout (keeps
    # the output clean for the LLM). The command text is the batch
    # body; trailing newline keeps the last line from being eaten.
    bat_path: str | None = None
    try:
        fd, bat_path = tempfile.mkstemp(suffix=".bat")
        with os.fdopen(fd, "wb") as f:
            f.write(_encode_bat("@echo off\r\n" + command + "\r\n"))
    except OSError as e:
        yield (
            f"[error:env] failed to create temp batch file: {type(e).__name__}: {e}. "
            "hint: check that %TEMP% is writable; do not retry as-is."
        )
        return

    # ---- spawn ------------------------------------------------------
    # /d: skip AutoRun commands (fast + predictable).
    # /c: run the batch file then exit.
    # The batch path is passed as a plain argument — no quoting rules
    # to fight because the command itself lives in the file.
    try:
        proc = await asyncio.create_subprocess_exec(
            CMD_EXE,
            "/d",
            "/c",
            bat_path,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as e:
        # cmd.exe isn't on PATH — basically impossible on Windows but
        # keep the branch for symmetry with the PowerShell tool.
        yield (
            f"[error:env] cmd.exe not found on PATH ({e}). "
            "hint: cmd.exe ships with every Windows install; if it's missing, "
            "the system is broken and needs repair. Do not retry."
        )
        return
    except PermissionError as e:
        yield (
            f"[error:env] permission denied launching cmd.exe: {e}. "
            "hint: try a less-restricted process or ask the user to run mhc-desktop as Administrator. Do not retry as-is."
        )
        return
    except OSError as e:
        yield (
            f"[error:env] failed to spawn cmd.exe: {type(e).__name__}: {e}. "
            "hint: this is an environment-level issue (PATH, ACL, or antivirus blocking). Do not retry."
        )
        return

    # Close stdin immediately — the batch file is the input, cmd
    # shouldn't wait on our pipe at all.
    assert proc.stdin is not None
    try:
        proc.stdin.close()
    except Exception:
        pass

    # ---- streaming loop --------------------------------------------
    # Two concurrent readers (stdout line-by-line, stderr fully
    # buffered) plus the timeout. We kill the child on any exit
    # path: success, timeout, cancellation, or read error.
    try:

        async def _read_stdout() -> list[str]:
            assert proc.stdout is not None
            lines: list[str] = []
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                lines.append(_decode_out(line))
            return lines

        async def _read_stderr() -> str:
            assert proc.stderr is not None
            data = await proc.stderr.read()
            return _decode_out(data)

        async def _wait() -> None:
            await proc.wait()

        stdout_task = asyncio.create_task(_read_stdout())
        stderr_task = asyncio.create_task(_read_stderr())
        wait_task = asyncio.create_task(_wait())

        try:
            done, pending = await asyncio.wait(
                {stdout_task, stderr_task, wait_task},
                timeout=timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
        except asyncio.CancelledError:
            # User clicked stop (or another tool bumped our session).
            # Kill the child and wait for the kernel to fully reap it
            # *before* the loop closes — otherwise asyncio's
            # subprocess transport raises "Event loop is closed"
            # warnings during GC and the pipe fds leak for a moment.
            await _kill_proc(proc)
            for t in (stdout_task, stderr_task, wait_task):
                if not t.done():
                    t.cancel()
            try:
                await proc.wait()
            except Exception:
                pass
            raise

        if not done:
            # Timeout fired. Kill the child and surface a clear
            # error to the LLM.
            await _kill_proc(proc)
            for t in (stdout_task, stderr_task, wait_task):
                if not t.done():
                    t.cancel()
            try:
                await proc.wait()
            except Exception:
                pass
            yield f"[timeout] cmd did not finish within {timeout}s; killed\n"
            return

        # Drain whichever finished first.
        stdout_lines: list[str] = []
        stderr_text: str = ""
        if stdout_task in done:
            stdout_lines = stdout_task.result()
        if stderr_task in done:
            stderr_text = stderr_task.result()

        # Wait for the rest, with a small grace period (no extra
        # timeout — the child should already be done or very close).
        remaining = {t for t in (stdout_task, stderr_task, wait_task) if not t.done()}
        if remaining:
            await asyncio.wait(remaining, timeout=2.0)
            if stdout_task.done() and not stdout_lines:
                try:
                    stdout_lines = stdout_task.result()
                except Exception:
                    pass
            if stderr_task.done() and not stderr_text:
                try:
                    stderr_text = stderr_task.result()
                except Exception:
                    pass

        # Emit collected stdout line-by-line so partial progress
        # reaches the chat UI before the final exit marker.
        for line in stdout_lines:
            yield line

        if stderr_text.strip():
            yield f"[stderr]\n{stderr_text}\n[/stderr]\n"

        exit_code = proc.returncode
        if exit_code is None:
            # Still alive? shouldn't be after wait() resolved, but
            # be defensive.
            yield "[error] cmd exited with unknown status\n"
        elif exit_code != 0:
            yield f"[exit {exit_code}]\n"
        # exit 0: stay quiet; the output speaks for itself.
    except asyncio.CancelledError:
        # Re-raise so chat.py's cancel handling takes over. The
        # finally block below still runs and kills the child.
        raise
    except Exception as e:
        # Anything that wasn't a validation / spawn / timeout
        # error is unexpected. Surface it with the exception
        # class so the model has a clue, and include any output
        # already collected (stdout, stderr) so partial progress
        # isn't lost. We don't know whether retrying helps —
        # tell the model so it can decide.
        partial_stdout = "".join(stdout_lines) if "stdout_lines" in locals() else ""
        partial_stderr = (
            stderr_text if "stderr_text" in locals() and stderr_text else ""
        )
        yield (
            f"[error] unexpected cmd failure: {type(e).__name__}: {e}\n"
            "hint: this wasn't a validation, timeout, or spawn error — "
            "could be a broken pipe, an OS kill mid-run, or a bug in the tool. "
            "If the command worked before, retry once; if it keeps failing, "
            "ask the user to check the system or pick a different approach."
        )
        if partial_stdout:
            yield f"[partial-stdout]\n{partial_stdout}\n[/partial-stdout]\n"
        if partial_stderr:
            yield f"[partial-stderr]\n{partial_stderr}\n[/partial-stderr]\n"
        return
    finally:
        # Catch-all: if any of the above branches left the child
        # alive (e.g. an unexpected exception while reading), make
        # sure it dies and is reaped before we yield control back
        # to the event loop. Without this, a stuck cmd would
        # keep running until the backend shut down.
        if proc.returncode is None:
            await _kill_proc(proc)
        try:
            await proc.wait()
        except Exception:
            pass
        # Clean up the temp batch file on every exit path.
        if bat_path is not None:
            try:
                os.unlink(bat_path)
            except OSError:
                pass


async def _kill_proc(proc: asyncio.subprocess.Process) -> None:
    """Best-effort kill for the cmd child AND its process tree.

    cmd.exe ``/c <bat>`` waits for the batch's own child processes
    (e.g. ``ping``, ``robocopy``) to finish. Killing only cmd.exe
    orphans those children — and because the children inherited the
    stdout/stderr pipes, asyncio's ``proc.wait()`` then blocks until
    they exit on their own (a 60-ping can hang the timeout for a
    minute). ``taskkill /T /F`` terminates the whole tree, which
    closes the pipes and lets ``proc.wait()`` return immediately.

    Falls back to ``proc.kill()`` if taskkill itself can't run.
    """
    pid = getattr(proc, "pid", None)
    if pid is None:
        try:
            proc.kill()
        except Exception:
            pass
        return
    try:
        # taskkill.exe ships with Windows; /T kills the whole tree,
        # /F is forceful. This is a separate process so killing it
        # doesn't touch our own tree. Wait a short grace period so
        # the OS has reaped the pipes before the caller's
        # ``await proc.wait()`` below.
        killer = await asyncio.create_subprocess_exec(
            "taskkill",
            "/PID",
            str(pid),
            "/T",
            "/F",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(killer.wait(), timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


# A `run` alias matches what the importer looks for alongside
# `tool_run` — see tools.imports._resolve_callable. Tools that
# don't expose `tool_run` get matched against `run` / `main` /
# `callable` in that order. We expose both so re-imports don't
# break.
async def run(*args: Any, **kwargs: Any) -> AsyncIterator[str]:
    async for chunk in tool_run(*args, **kwargs):
        yield chunk
