"""Skill subsystem exception types.

``SkillError`` lives in the kernel because the chat router and skill
API both ``except`` it. The concrete file-backed
:class:`mhc_desktop_deploy.impls.file_stores.skills_store.SkillStore`
raises it; enterprise adapters should raise the same exception so
``except SkillError`` catches their failures too.
"""

from __future__ import annotations


class SkillError(ValueError):
    """Caller-facing error (validation, IO, conflict)."""


__all__ = ["SkillError"]
