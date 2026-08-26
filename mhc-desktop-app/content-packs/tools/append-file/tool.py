"""Append content to the end of an existing file.

Parameters (all keyword-only):

* ``path``    (string)  — file to append to (required, must exist)
* ``content`` (string)  — text to append (required; may be empty)

Execution model:

* Appends in UTF-8; never touches the existing content.
* In-process and fast — no subprocess, no temp files.

Use this instead of shell ``>>`` redirection for appending. If the
file does not exist, create it with write-file first — appending to
a missing file is an error, not a silent create, so a typo'd path
surfaces instead of spawning an empty file somewhere unexpected.

Errors are formatted semantically so the model can recover on the
next call:
  * ``[error:bad-arg]``  — fix the argument and retry
  * ``[error]``          — file missing / OS failure; message has the detail
"""

from __future__ import annotations

import os
from typing import Any, AsyncIterator


async def tool_run(*, path: str = "", content: str = "") -> AsyncIterator[str]:
    # ---- argument validation ---------------------------------------
    if not isinstance(path, str) or not path.strip():
        yield (
            "[error:bad-arg] path must be a non-empty string. "
            "hint: pass the file path, e.g. 'C:/Users/me/notes.txt' or './src/main.py'"
        )
        return
    if not isinstance(content, str):
        yield (
            f"[error:bad-arg] content must be a string; got {type(content).__name__}. "
            "hint: pass the text to append as a string"
        )
        return

    if not os.path.isfile(path):
        yield (
            f"[error] file not found: {path}. "
            "hint: use write-file to create the file first, then append to it"
        )
        return

    try:
        with open(path, "a", encoding="utf-8", newline="") as f:
            f.write(content)
    except OSError as e:
        yield f"[error] failed to append to {path}: {type(e).__name__}: {e}"
        return

    yield f"Appended {len(content)} characters to {path}\n"


# A `run` alias matches what the importer looks for alongside
# `tool_run` — see tools.imports._resolve_callable. Tools that
# don't expose `tool_run` get matched against `run` / `main` /
# `callable` in that order. We expose both so re-imports don't
# break.
async def run(*args: Any, **kwargs: Any) -> AsyncIterator[str]:
    async for chunk in tool_run(*args, **kwargs):
        yield chunk
