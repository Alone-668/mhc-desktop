"""Default file-backed concrete stores.

Each top-level constant / function in this package returns one
ready-to-use instance of the corresponding store Protocol. They are
the only concrete implementations a default deploy wires up; enterprise
deploys substitute their own at the ``create_app(...)`` call site.

Module layout mirrors the kernel Protocol names so it's obvious
which file backs which slot:

* ``paths`` — ``DATA_DIR``, ``PREFS_FILE``, etc.
* ``provider_store`` — :class:`ProviderStoreProtocol`
* ``session_store`` — :class:`SessionStoreProtocol`
* ``skill_store`` — :class:`SkillStoreProtocol`
* ``mcp_store`` — :class:`MCPStoreProtocol`
* ``tools_store`` — :class:`ToolStoreProtocol`
* ``prefs_store`` — :class:`PrefsStoreProtocol`
* ``metrics_store`` — :class:`MetricsRepositoryProtocol`
* ``stream_registry`` — :class:`StreamRegistryProtocol`
* ``mcp_manager`` — :class:`MCPManagerProtocol` (wraps :class:`mcp_store`)
"""

from __future__ import annotations

from mhc_desktop_deploy.impls.file_stores._defaults import (
    default_mcp_manager,
    default_mcp_store,
    default_metrics_repo,
    default_prefs_store,
    default_provider_store,
    default_session_store,
    default_skill_store,
    default_stream_registry,
    default_tool_store,
)
from mhc_desktop_deploy.impls.file_stores.paths import ensure_dirs

__all__ = [
    "default_mcp_manager",
    "default_mcp_store",
    "default_metrics_repo",
    "default_prefs_store",
    "default_provider_store",
    "default_session_store",
    "default_skill_store",
    "default_stream_registry",
    "default_tool_store",
    "ensure_dirs",
]
