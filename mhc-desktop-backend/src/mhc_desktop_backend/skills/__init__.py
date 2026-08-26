"""Skills subsystem.

Public surface used by the API router and chat handler:

* :class:`SkillStore` — disk-backed CRUD on installed skills
* :class:`SkillError` — caller-facing error type
* :func:`format_skill_message` — renders one skill as a single
  user-role message body (used by the chat handler)
"""

from __future__ import annotations

from mhc_desktop_backend.skills.errors import SkillError
from mhc_desktop_backend.skills.frontmatter import (
    FrontmatterError,
    SkillFrontmatter,
    parse_skill_md,
    render_skill_md,
)
from mhc_desktop_backend.skills.models import Skill

# ``SkillStore`` (the concrete class) moved to
# ``mhc_desktop_deploy.impls.file_stores.skills_store``. Callers
# should depend on :class:`mhc_desktop_backend.protocols.SkillStoreProtocol`
# instead — the kernel never imports the concrete class.
__all__ = [
    "Skill",
    "SkillError",
    "SkillFrontmatter",
    "FrontmatterError",
    "parse_skill_md",
    "render_skill_md",
    "format_skill_message",
]


def format_skill_message(skill: Skill) -> str:
    """Render one skill as a single user-role message body.

    The chat handler sends this as a ``user``-role message right
    before the user's actual input. Labeling is explicit so the model
    understands the block isn't a regular user message — it's the
    user attaching a skill for this turn.

    Includes:
    * ``description`` (Anthropic's "when to use" trigger)
    * the markdown body
    * a listing of attached files plus their inlined contents
      (added by :func:`mhc_desktop_backend.api.chat._inline_skill_files`
      before this is called)
    * a closing instruction that asks the model to apply the skill
      in its reply to the user's input below
    """
    header = f"[Attached skill: {skill.name} (`{skill.slug}`)]"
    desc = (skill.description or "").strip()
    sections: list[str] = [header]
    if desc:
        sections.append(f"**When to use:** {desc}")
    sections.append(skill.body or "(skill has no body)")
    if skill.files:
        listing = "\n".join(f"- `{f}`" for f in skill.files)
        sections.append(f"**Attached files (read inline below):**\n{listing}")
    sections.append("Apply this skill's rules in your reply to the user's input below.")
    return "\n\n".join(sections)
