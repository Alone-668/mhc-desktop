"""Run a shell command in Windows PowerShell.

Two required parameters:

* ``command``  (string)  — the exact PowerShell expression to run
* ``timeout``  (int)     — per-call ceiling in seconds, hard cap 600

Execution model:

* Spawns ``powershell.exe -NoProfile -NonInteractive -Command <cmd>``
  via ``asyncio.create_subprocess_exec`` so the backend event loop
  stays responsive while the child runs.
* Streams stdout line-by-line so the LLM sees partial output before
  the process exits. stderr is buffered and appended at the end so
  errors don't get lost in a chatty stdout stream.
* Capped by an internal ``asyncio.wait_for`` at ``timeout`` seconds.
* Always cleans up: any cancellation (user clicked "stop") or
  timeout kills the child process before we return. The backend's
  ``run_tool`` wrapper races the runner task against a cancel event
  and will inject ``CancelledError`` into this function — the
  ``finally`` block ensures the PowerShell child dies with it.

Hard cap on ``timeout`` is 600 seconds (10 min). The chat layer
already has its own 15-minute safety net above this, so even a
misbehaving timeout argument cannot hang the session.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any, AsyncIterator

# Maximum timeout we'll honour from a tool call. Anything higher
# would defeat the purpose — a runaway tool shouldn't survive long
# enough to need it, and longer-lived tasks belong in a script, not
# a chat invocation.
MAX_TIMEOUT_SECONDS = 600

# Default if the manifest supplies one. The model is expected to
# always pass timeout explicitly; this is just the schema default.
DEFAULT_TIMEOUT_SECONDS = 60

# Powershell location. We look it up explicitly so a missing
# executable surfaces as a clean error message instead of a
# FileNotFoundError stack trace.
if sys.platform != "win32":
    POWERSHELL_EXE = ""
else:
    # On Windows we always use Windows PowerShell 5.x for broadest
    # compatibility — powershell.exe ships with the OS. pwsh.exe
    # (PowerShell 7) is *not* assumed to be present.
    POWERSHELL_EXE = "powershell.exe"


async def tool_run(*, command: str, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> AsyncIterator[str]:
    """Run ``command`` in PowerShell and stream stdout.

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
        yield "[error:bad-arg] command must be a string (got " + type(command).__name__ + ")"
        return
    if not command.strip():
        yield (
            "[error:bad-arg] command must be a non-empty PowerShell expression. "
            "hint: pass a real command, e.g. 'Get-Date' or 'Get-Process | Select-Object -First 3'"
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
            f"[error:env] powershell tool only runs on Windows (this host is {sys.platform}). "
            "hint: this is a host limitation — calling powershell on Linux/macOS will always fail"
        )
        return

    # ---- spawn ------------------------------------------------------
    # -NoProfile: skip loading the user's profile.ps1 (fast + predictable).
    # -NonInteractive: don't prompt for input even if the command tries to.
    # -ExecutionPolicy Bypass: run without prompting about script signing.
    # -Command -: read the command from stdin so we don't have to escape
    #   it for the -Command "<string>" form (which has its own quoting
    #   rules and surprises with embedded quotes / dollar signs).
    try:
        proc = await asyncio.create_subprocess_exec(
            POWERSHELL_EXE,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            "-",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as e:
        # powershell.exe isn't on PATH (or App Execution Aliases is
        # misconfigured). This is permanent — retrying without user
        # action won't help. Surface it clearly so the model doesn't
        # loop.
        yield (
            f"[error:env] powershell.exe not found on PATH ({e}). "
            "hint: Windows PowerShell ships with Windows; if it's missing, "
            "the user needs to enable 'App Execution Aliases' for PowerShell "
            "in Windows Settings or repair the OS installation. Do not retry."
        )
        return
    except PermissionError as e:
        yield (
            f"[error:env] permission denied launching powershell.exe: {e}. "
            "hint: try a less-restricted process or ask the user to run mhc-desktop as Administrator. Do not retry as-is."
        )
        return
    except OSError as e:
        yield (
            f"[error:env] failed to spawn powershell.exe: {type(e).__name__}: {e}. "
            "hint: this is an environment-level issue (PATH, ACL, or antivirus blocking). Do not retry."
        )
        return

    # Feed the command in immediately and close stdin so PowerShell
    # reaches its end-of-input and runs it.
    assert proc.stdin is not None
    try:
        proc.stdin.write(command.encode("utf-8"))
        await proc.stdin.drain()
    except (BrokenPipeError, ConnectionResetError):
        # The child died before we could finish writing; the loop
        # below will report its exit code.
        pass
    finally:
        try:
            proc.stdin.close()
        except Exception:
            pass

    # ---- streaming loop --------------------------------------------
    # Two concurrent readers (stdout line-by-line, stderr fully
    # buffered) plus the timeout. We kill the child on any exit
    # path: success, timeout, cancellation, or read error.
    timeout_handle: asyncio.TimerHandle | None = None
    try:
        async def _read_stdout() -> list[str]:
            assert proc.stdout is not None
            lines: list[str] = []
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                lines.append(line.decode("utf-8", errors="replace"))
            return lines

        async def _read_stderr() -> str:
            assert proc.stderr is not None
            data = await proc.stderr.read()
            return data.decode("utf-8", errors="replace")

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
            _kill_proc(proc)
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
            _kill_proc(proc)
            for t in (stdout_task, stderr_task, wait_task):
                if not t.done():
                    t.cancel()
            try:
                await proc.wait()
            except Exception:
                pass
            yield f"[timeout] powershell did not finish within {timeout}s; killed\n"
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
            yield "[error] powershell exited with unknown status\n"
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
            f"[error] unexpected powershell failure: {type(e).__name__}: {e}\n"
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
        # to the event loop. Without this, a stuck PowerShell would
        # keep running until the backend shut down.
        if proc.returncode is None:
            _kill_proc(proc)
        try:
            await proc.wait()
        except Exception:
            pass


def _kill_proc(proc: asyncio.subprocess.Process) -> None:
    """Best-effort kill for the PowerShell child.

    On Windows ``Process.kill()`` calls ``TerminateProcess`` which
    is forceful enough for our purposes; ``CTRL_BREAK_EVENT`` would
    be cleaner but isn't wired into asyncio's subprocess API and
    PowerShell can ignore it for non-interactive runs anyway.
    """
    try:
        proc.kill()
    except ProcessLookupError:
        pass
    except Exception:
        # Don't let cleanup mask the original error.
        pass


# A `run` alias matches what the importer looks for alongside
# `tool_run` — see tools.imports._resolve_callable. Tools that
# don't expose `tool_run` get matched against `run` / `main` /
# `callable` in that order. We expose both so re-imports don't
# break.
async def run(*args: Any, **kwargs: Any) -> AsyncIterator[str]:
    async for chunk in tool_run(*args, **kwargs):
        yield chunk