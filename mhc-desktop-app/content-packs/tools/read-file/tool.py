"""Read a text file, optionally paging by line range.

Parameters (all keyword-only):

* ``path``   (string)  — path to the text file to read (required)
* ``offset`` (int)     — 1-based first line to return (default 1)
* ``limit``  (int)     — max lines to return (default 2000; 0 = no limit)

Execution model:

* Reads with UTF-8 (undecodable bytes replaced, never fatal) so any
  text file — logs, configs, source code, even most GBK/ANSI files
  whose bytes happen to be valid UTF-8 — is returned verbatim.
* Default ``limit`` 2000 pages large files; when a page is
  truncated the final chunk tells the model the next ``offset`` so
  a follow-up call continues where it left off.
* A single read is fast and bounded — no subprocess, no temp files,
  nothing to clean up on cancellation.

Errors are formatted semantically so the model can recover on the
next call:
  * ``[error:bad-arg]``  — fix the argument and retry
  * ``[error]``          — file missing / unreadable; message has the detail
"""

from __future__ import annotations

import os
from itertools import islice
from typing import Any, AsyncIterator


async def tool_run(
    *, path: str = "", offset: int = 1, limit: int = 2000
) -> AsyncIterator[str]:
    # ---- argument validation ---------------------------------------
    if not isinstance(path, str) or not path.strip():
        yield (
            "[error:bad-arg] path must be a non-empty string. "
            "hint: pass the file path, e.g. 'C:/Users/me/notes.txt' or './src/main.py'"
        )
        return
    if isinstance(offset, bool) or not isinstance(offset, int):
        yield (
            f"[error:bad-arg] offset must be an integer (1-based line number); got {type(offset).__name__} {offset!r}. "
            "hint: omit the field to start at line 1"
        )
        return
    if isinstance(limit, bool) or not isinstance(limit, int):
        yield (
            f"[error:bad-arg] limit must be an integer (max lines); got {type(limit).__name__} {limit!r}. "
            "hint: omit the field for the default 2000, or pass 0 for no limit"
        )
        return

    if not os.path.isfile(path):
        yield f"[error] file not found: {path}"
        return

    start = max(int(offset), 1) - 1
    max_lines = None if int(limit) <= 0 else int(limit)

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            skipped = sum(1 for _ in islice(f, start))
            if max_lines is None:
                selected = list(f)
                rest = 0
            else:
                selected = list(islice(f, max_lines))
                rest = sum(1 for _ in f)
    except OSError as e:
        yield f"[error] failed to read {path}: {type(e).__name__}: {e}"
        return

    total = skipped + len(selected) + rest
    truncated = rest > 0
    for line in selected:
        yield line
    if truncated:
        nxt = skipped + len(selected) + 1
        yield (
            f"\n[truncated] returned lines {skipped + 1}-{skipped + len(selected)} "
            f"of {total}; call read-file again with offset={nxt} for the next page\n"
        )


# A `run` alias matches what the importer looks for alongside
# `tool_run` — see tools.imports._resolve_callable. Tools that
# don't expose `tool_run` get matched against `run` / `main` /
# `callable` in that order. We expose both so re-imports don't
# break.
async def run(*args: Any, **kwargs: Any) -> AsyncIterator[str]:
    async for chunk in tool_run(*args, **kwargs):
        yield chunk
