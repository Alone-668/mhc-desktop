"""Tool subsystem exception types.

``ToolStoreError`` lives in the kernel because the chat router and
tool API both ``except`` it. The concrete file-backed
:class:`mhc_desktop_deploy.impls.file_stores.tools_store.ToolStore`
raises it; enterprise adapters should raise the same type.
"""

from __future__ import annotations


class ToolStoreError(Exception):
    """Caller-facing error type for store mutations."""


__all__ = ["ToolStoreError"]
