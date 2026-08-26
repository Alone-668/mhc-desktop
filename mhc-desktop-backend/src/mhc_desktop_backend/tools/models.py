"""Tool config + metadata for the local / imported / remote tool catalog.

A ``Tool`` is an executable unit the model can call during an agent
run. Three kinds, mirroring ``minimal_harness``'s binding union:

* ``local`` — an in-process Python async callable. Bundled tools ship
  this way. Imported tools can be either this or ``script``.
* ``script`` — an external Python file the backend imports and calls.
  Stored verbatim under ``tools/<slug>/tool.py`` so the import path is
  reproducible across restarts.
* ``remote`` — an SSE-over-HTTP endpoint. ``endpoint_url`` is the URL
  the backend dials; ``endpoint_auth_header`` is an optional
  ``Authorization: ...`` value the user pastes in.

The ``parameters`` field is the JSON schema for the tool's input —
passed verbatim to the LLM as the tool schema.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

ToolKind = Literal["local", "script", "remote"]

_NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9_-]{0,62}[a-z0-9])?$")


def slugify(name: str) -> str:
    n = name.strip().lower()
    n = re.sub(r"[^a-z0-9_-]+", "-", n)
    n = re.sub(r"-+", "-", n).strip("-")
    return n[:64] or "tool"


def is_valid_slug(name: str) -> bool:
    """Reject slugs that would collide with the MCP convention of
    ``<slug>::<tool>``. We don't allow ``::`` in tool names — it's
    reserved for MCP namespacing so the chat handler can tell the two
    kinds apart without inspecting event payloads.
    """
    if not _NAME_RE.match(name):
        return False
    if "::" in name:
        return False
    return True


@dataclass
class Tool:
    """Persistent spec for one tool the model can call.

    Three identifiers, three jobs:
    - ``id``        — system primary key (UUID, stable, never reused)
    - ``slug``      — URL-safe identifier used in API routes
    - ``name``      — user-facing display name (may contain spaces,
                       may be renamed freely)
    - ``model_name`` — name passed to the LLM as the callable's
                       ``function.name``. Defaults to ``slug`` so the
                       LLM sees a stable, slug-shaped identifier
                       independent of the display name (which the
                       user may rename at any time).
    """

    id: str = ""
    slug: str = ""
    name: str = ""
    description: str = ""
    kind: ToolKind = "local"
    parameters: dict[str, Any] = field(default_factory=dict)
    # Remote-only — the SSE endpoint the backend dials.
    endpoint_url: str = ""
    # Script-only — the relative path inside the tool's directory.
    script_path: str = "tool.py"
    # Auth header for remote calls. Stored as-is, never logged.
    endpoint_auth_header: str = ""
    # What the LLM sees as the function name. Empty defaults to slug.
    model_name: str = ""
    enabled: bool = True
    origin: str = "imported"  # "bundled" | "imported" | "local"
    # Localized display names keyed by language tag (e.g. "en",
    # "zh"). The LLM never sees these — they are for the UI.
    # An empty dict / missing key falls back to ``name``.
    display_name_i18n: dict[str, str] = field(default_factory=dict)
    source_path: str = ""
    version: str = ""
    license: str = ""
    created_at: str = ""
    updated_at: str = ""

    def ensure_id(self) -> None:
        """Backfill UUID on records predating the field."""
        if not self.id:
            self.id = str(uuid.uuid4())

    def resolved_model_name(self) -> str:
        """The name the LLM will actually see. Falls back to slug
        if the operator hasn't set a custom one."""
        return self.model_name.strip() or self.slug

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def public_dict(self) -> dict[str, Any]:
        """List-shape representation. We don't expose the auth header
        even to the list endpoint — the detail endpoint returns it
        separately, and only because the user is the one who set it.
        """
        d = self.to_dict()
        d.pop("endpoint_auth_header", None)
        return d


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def safe_join(root, *parts):
    """Reject path traversal the same way SkillStore / MCPStore do."""
    final = root.joinpath(*parts).resolve()
    try:
        final.relative_to(root.resolve())
    except ValueError as e:
        raise ValueError(f"path escapes root: {final}") from e
    return final
