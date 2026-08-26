"""MCP server config + tool catalog.

An ``MCPServer`` is a named connection spec (command + args + env)
that the chat handler can spawn to expose tools. The actual JSON-RPC
process is managed at runtime by :class:`MCPManager`.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

# Mirror the Skills.slug rules: lowercase-hyphen identifier. We don't
# expose this as user-facing config; the slug is the frontmatter name
# the user typed, derived from the config when saved.
_NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")


def slugify(name: str) -> str:
    n = name.strip().lower()
    n = re.sub(r"[^a-z0-9-]+", "-", n)
    n = re.sub(r"-+", "-", n).strip("-")
    return n[:64] or "mcp"


@dataclass
class MCPServer:
    """Persistent spec for one MCP server the user has configured.

    ``id`` is the system's primary key — a UUID generated at create
    time and stable for the lifetime of the entry. ``slug`` is the
    URL-safe identifier used in API routes. ``name`` is the
    user-facing display name.
    """

    id: str = ""
    slug: str = ""
    name: str = ""
    description: str = ""
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    origin: str = "imported"  # "imported" | "local"
    source_path: str = ""
    tools: list[dict[str, Any]] = field(default_factory=list)
    last_connected_at: str = ""
    last_error: str = ""
    created_at: str = ""
    updated_at: str = ""

    def ensure_id(self) -> None:
        """Backfill a UUID if this entry was loaded from an older
        disk record that predates the field. Idempotent."""
        if not self.id:
            self.id = str(uuid.uuid4())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def public_dict(self) -> dict[str, Any]:
        """List-shape representation. Drops nothing — the tool list is
        useful in the management page so the user can see what's
        exposed without having to connect first."""
        return self.to_dict()


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def is_valid_slug(name: str) -> bool:
    return bool(_NAME_RE.match(name))


def safe_join(root, *parts):
    """Reject path traversal the same way SkillStore does."""
    final = root.joinpath(*parts).resolve()
    try:
        final.relative_to(root.resolve())
    except ValueError as e:
        raise ValueError(f"path escapes root: {final}") from e
    return final
