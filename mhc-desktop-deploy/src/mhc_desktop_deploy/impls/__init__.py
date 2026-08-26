"""Concrete implementations of backend Protocols.

Sub-modules:

* :mod:`.file_stores` — JSON-file-backed reference implementations
  (sessions, providers, skills, MCP, tools, prefs, metrics, stream
  registry, paths).
* :mod:`.auth` — authentication providers (mock for now; real
  IdP adapters go in sibling modules).
"""

from __future__ import annotations
