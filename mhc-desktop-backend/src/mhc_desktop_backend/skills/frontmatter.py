"""Anthropic Skills frontmatter parser.

A skill folder must contain ``SKILL.md`` with YAML frontmatter:

    ---
    name: my-skill
    description: When to use this skill
    ---

    # body content follows

We accept the standard Anthropic names (``name`` and ``description``)
plus a couple of optional fields we use ourselves (``version``,
``license``). Anything else in the frontmatter is preserved verbatim
on the dataclass so users can extend without us shipping a parser.

Format spec reference:
https://docs.claude.com/en/docs/agents-and-tools/agent-skills/overview
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# Lazily imported yaml to keep module load cheap; if PyYAML is missing
# we still want this module importable so the rest of the app starts.
try:
    import yaml  # type: ignore[import-untyped]

    _HAVE_YAML = True
except Exception:  # pragma: no cover - depends on environment
    yaml = None  # type: ignore[assignment]
    _HAVE_YAML = False


def _yaml():
    """Return the (imported) yaml module.

    PyYAML is a hard dependency of the backend, so this should always
    succeed. We keep the lazy import + fallback for environments where
    yaml isn't installed (e.g. a partial test install).
    """
    if not _HAVE_YAML or yaml is None:  # pragma: no cover
        raise FrontmatterError("PyYAML not installed; cannot parse SKILL.md")
    return yaml


@dataclass
class SkillFrontmatter:
    """Frontmatter block of a SKILL.md file."""

    name: str = ""
    description: str = ""
    version: str = ""
    license: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> list[str]:
        """Return a list of validation errors (empty = OK)."""
        errors: list[str] = []
        if not self.name:
            errors.append("name is required")
        elif not _NAME_RE.match(self.name):
            errors.append(
                "name must be lowercase letters, digits, and hyphens "
                "(start/end with letter or digit, no consecutive hyphens)"
            )
        elif len(self.name) > 64:
            errors.append("name must be 64 characters or fewer")
        if not self.description:
            errors.append("description is required")
        elif len(self.description) > 1024:
            errors.append("description must be 1024 characters or fewer")
        return errors


_NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
_FRONTMATTER_RE = re.compile(
    r"\A---\s*\n(.*?)\n---\s*(?:\n|$)(.*)\Z",
    re.DOTALL,
)


class FrontmatterError(ValueError):
    """Raised when SKILL.md frontmatter is missing or malformed."""


def parse_skill_md(text: str) -> tuple[SkillFrontmatter, str]:
    """Split a SKILL.md file into (frontmatter, body).

    Body is the markdown following the closing ``---`` delimiter. If no
    frontmatter block is present we return an empty frontmatter and the
    full text as the body, so the caller can decide what to do.

    Raises ``FrontmatterError`` if the YAML between the delimiters is
    not a mapping (e.g. someone put a string or list there).
    """
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return SkillFrontmatter(), text

    raw_yaml, body = m.group(1), m.group(2)
    parsed = _yaml().safe_load(raw_yaml) or {}
    if not isinstance(parsed, dict):
        raise FrontmatterError(
            "SKILL.md frontmatter must be a YAML mapping "
            "(e.g. 'name:' / 'description:')"
        )

    fm = SkillFrontmatter(
        name=str(parsed.get("name", "")).strip(),
        description=str(parsed.get("description", "")).strip(),
        version=str(parsed.get("version", "")).strip(),
        license=str(parsed.get("license", "")).strip(),
    )
    # Preserve anything else verbatim — useful for downstream tooling
    # without forcing us to keep a parser in sync.
    known = {"name", "description", "version", "license"}
    fm.extra = {k: v for k, v in parsed.items() if k not in known}
    return fm, body.lstrip("\n")


def render_skill_md(fm: SkillFrontmatter, body: str) -> str:
    """Inverse of :func:`parse_skill_md`. Used when editing metadata
    through the UI without losing the body."""
    out: dict[str, Any] = {"name": fm.name, "description": fm.description}
    if fm.version:
        out["version"] = fm.version
    if fm.license:
        out["license"] = fm.license
    out.update(fm.extra)
    if not _HAVE_YAML:  # pragma: no cover
        raise FrontmatterError("PyYAML not installed; cannot write SKILL.md")
    yaml_text = _yaml().safe_dump(out, sort_keys=False, allow_unicode=True).rstrip()
    body = body.lstrip("\n").rstrip() + "\n"
    return f"---\n{yaml_text}\n---\n\n{body}"
