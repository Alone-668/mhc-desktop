"""Replace exact text in an existing file (find-and-replace).

Parameters (all keyword-only):

* ``path``       (string)  — file to edit (required, must exist)
* ``old_string`` (string)  — exact text to replace (required)
* ``new_string`` (string)  — replacement text (required; may be empty)

Execution model:

* Reads the whole file, does an exact ``str.replace`` (every
  occurrence), writes back, and yields a unified diff so the model
  can verify what changed without a separate read-file call.
* Whitespace and line endings must match the file exactly — the
  diff shows the real content when a match fails, so the model can
  copy the precise text and retry.
* In-process and fast — no subprocess, no temp files.

Use this instead of sed/perl one-liners for targeted edits.

Errors are formatted semantically so the model can recover on the
next call:
  * ``[error:bad-arg]``  — fix the argument and retry
  * ``[error]``          — file missing / old_string not found / OS failure
"""

from __future__ import annotations

import difflib
import os
from typing import Any, AsyncIterator


async def tool_run(
    *, path: str = "", old_string: str = "", new_string: str = ""
) -> AsyncIterator[str]:
    # ---- argument validation ---------------------------------------
    if not isinstance(path, str) or not path.strip():
        yield (
            "[error:bad-arg] path must be a non-empty string. "
            "hint: pass the file path, e.g. 'C:/Users/me/notes.txt' or './src/main.py'"
        )
        return
    if not isinstance(old_string, str) or not old_string:
        yield (
            "[error:bad-arg] old_string must be a non-empty string. "
            "hint: pass the exact text to replace (whitespace and line endings must match the file)"
        )
        return
    if not isinstance(new_string, str):
        yield (
            f"[error:bad-arg] new_string must be a string; got {type(new_string).__name__}. "
            "hint: pass the replacement text as a string (empty string deletes the old text)"
        )
        return

    if not os.path.isfile(path):
        yield f"[error] file not found: {path}"
        return

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            data = f.read()
    except OSError as e:
        yield f"[error] failed to read {path}: {type(e).__name__}: {e}"
        return

    if old_string not in data:
        yield (
            f"[error] old_string not found in {path}. "
            "hint: read the file first (read-file), then copy the exact text into "
            "old_string — whitespace and line endings must match. Content preview:\n"
            + data[:500]
        )
        return

    count = data.count(old_string)
    new_data = data.replace(old_string, new_string)
    diff_lines = list(
        difflib.unified_diff(
            data.splitlines(keepends=True),
            new_data.splitlines(keepends=True),
            fromfile=path,
            tofile=path,
            lineterm="",
        )
    )

    try:
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(new_data)
    except OSError as e:
        yield f"[error] failed to write {path}: {type(e).__name__}: {e}"
        return

    yield f"Replaced {count} occurrence(s) in {path}:\n"
    for line in diff_lines:
        yield line


# A `run` alias matches what the importer looks for alongside
# `tool_run` — see tools.imports._resolve_callable. Tools that
# don't expose `tool_run` get matched against `run` / `main` /
# `callable` in that order. We expose both so re-imports don't
# break.
async def run(*args: Any, **kwargs: Any) -> AsyncIterator[str]:
    async for chunk in tool_run(*args, **kwargs):
        yield chunk
