"""Thin factory shim around the kernel's :class:`MCPManager`.

The kernel owns :class:`mhc_desktop_backend.mcp.MCPManager` because
it depends on ``minimal_harness`` + the ``MCPError`` exception type
(both kernel-side). The factory wiring lives in deploy because the
specific store instance it gets wrapped around is a deploy
implementation.

Customers swapping MCPStore for a Postgres-backed one replace
``default_mcp_store()`` with their own; the manager doesn't care.
"""

from __future__ import annotations

from mhc_desktop_backend.mcp import MCPManager

from mhc_desktop_deploy.impls.file_stores.mcp_store import MCPStore

__all__ = ["MCPManager", "MCPStore"]
