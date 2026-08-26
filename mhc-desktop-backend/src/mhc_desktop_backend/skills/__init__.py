"""Skills subsystem.

Public surface used by the API router and chat handler:

* :class:`SkillStore` — disk-backed CRUD on installed skills
* :class:`SkillError` — caller-facing error type
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
]
