"""Create a new file or overwrite an existing file with given content.

Parameters (all keyword-only):

* ``path``    (string)  — file to create or overwrite (required)
* ``content`` (string)  — full text to write (required; may be empty)

Execution model:

* Parent directories are created automatically — the model does not
  need a separate mkdir step.
* Written as UTF-8; a byte-for-byte replacement of any prior content.
* In-process and fast — no subprocess, no temp files, nothing to
  clean up on cancellation.

Use this instead of shell redirection (``echo > file``) for writing
files — the model's content is passed verbatim, with no quoting or
encoding surprises.

Errors are formatted semantically so the model can recover on the
next call:
  * ``[error:bad-arg]``  — fix the argument and retry
  * ``[error]``          — OS failure; message has the detail
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
            "hint: pass the full text to write as a string"
        )
        return

    # ---- create parent directories --------------------------------
    parent = os.path.dirname(path)
    created_parent = False
    if parent and not os.path.isdir(parent):
        try:
            os.makedirs(parent, exist_ok=True)
            created_parent = True
        except OSError as e:
            yield (
                f"[error] failed to create parent directory {parent}: "
                f"{type(e).__name__}: {e}"
            )
            return

    # ---- write -----------------------------------------------------
    try:
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(content)
    except OSError as e:
        yield f"[error] failed to write {path}: {type(e).__name__}: {e}"
        return

    msg = f"Wrote {len(content)} characters to {path}"
    if created_parent:
        msg += f" (created parent directory {parent})"
    yield msg + "\n"


# A `run` alias matches what the importer looks for alongside
# `tool_run` — see tools.imports._resolve_callable. Tools that
# don't expose `tool_run` get matched against `run` / `main` /
# `callable` in that order. We expose both so re-imports don't
# break.
async def run(*args: Any, **kwargs: Any) -> AsyncIterator[str]:
    async for chunk in tool_run(*args, **kwargs):
        yield chunk
