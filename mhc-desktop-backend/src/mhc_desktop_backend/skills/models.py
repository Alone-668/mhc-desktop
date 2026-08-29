"""Skill dataclass + serializers.

A skill is a folder containing ``SKILL.md`` (with YAML frontmatter)
plus any auxiliary files (``scripts/``, ``references/``, ``assets/``,
or anything else). User-visible state outside the folder itself —
the ``enabled`` flag, custom description overrides, source path — is
kept in a separate index file so importing a folder twice doesn't
overwrite user preferences.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
import uuid


@dataclass
class Skill:
    """In-memory representation of a single installed skill.

    ``id`` is a UUID generated at create time and is the system's
    primary key — never changes, never reused. ``slug`` is the
    on-disk directory name (matches ``frontmatter.name`` for any
    well-formed skill) and is the URL-safe identifier the API
    uses to address a skill in routes. ``name`` is the user-facing
    display name (may contain spaces, may be renamed freely)."""

    id: str = ""
    slug: str = ""
    name: str = ""
    description: str = ""
    body: str = ""
    files: list[str] = field(default_factory=list)
    enabled: bool = True
    origin: str = "imported"  # "imported" | "local"
    source_path: str = ""
    # On-disk location where this skill is actually installed
    # (``<skills_dir>/<slug>``). Distinct from ``source_path``,
    # which records where the skill was imported from.
    path: str = ""
    version: str = ""
    license: str = ""
    icon: str = ""  # from SKILL.md frontmatter ``icon:``; empty = letter avatar
    created_at: str = ""
    updated_at: str = ""

    def ensure_id(self) -> None:
        """Backfill ``id`` if loading from an older disk record that
        predates the field. Idempotent; safe to call on every load."""
        if not self.id:
            self.id = str(uuid.uuid4())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def public_dict(self) -> dict[str, Any]:
        """JSON-safe view used by the API (drops ``body`` for list view)."""
        d = asdict(self)
        # 'body' is big markdown; the list endpoint skips it. The
        # detail endpoint returns it separately.
        d.pop("body", None)
        return d


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def slugify(name: str) -> str:
    """Mirror the frontmatter name rules. Used when the user picks an
    arbitrary folder and we need a directory name."""
    import re

    name = name.strip().lower()
    name = re.sub(r"[^a-z0-9-]+", "-", name)
    name = re.sub(r"-+", "-", name).strip("-")
    return name[:64] or "skill"


def safe_join(root: Path, *parts: str) -> Path:
    """Join ``parts`` under ``root`` and refuse to escape ``root``.

    Used everywhere we accept a user-supplied relative path so a
    malicious ``../../etc/passwd`` can't reach the host filesystem.
    """
    final = root.joinpath(*parts).resolve()
    root_resolved = root.resolve()
    try:
        final.relative_to(root_resolved)
    except ValueError as e:
        raise ValueError(f"path escapes skill root: {final}") from e
    return final
