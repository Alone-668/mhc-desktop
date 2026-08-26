"""Built-in ``load_skill``. Bound to the live store at startup; the
chat handler invokes ``tool_run`` the same way it resolves any
other ``kind: "local"`` tool."""


from __future__ import annotations

from typing import Any, AsyncIterator, Protocol


class _SkillStoreLike(Protocol):
    async def get_body(self, slug: str) -> str | None: ...


# Bound by ensure_builtin_tools at startup; None for tests.
_skill_store: _SkillStoreLike | None = None


def set_skill_store(store: _SkillStoreLike | None) -> None:
    """Bind / unbind the live skill store. Called from app startup."""
    global _skill_store
    _skill_store = store


def _live_store():
    """``import_local_tool`` exec's source into a fresh namespace,
    so the binding lives in this module's real globals — re-import
    to read it."""
    import mhc_desktop_backend.tools.builtin.load_skill as _self
    return _self._skill_store


async def tool_run(slug: str) -> AsyncIterator[str]:
    """Yield the SKILL.md body at ``slug`` as a single chunk (the
chat handler wraps it into a ``role: "tool"`` message)."""
    store = _live_store()
    if store is None:
        yield (
            "[tool error] load_skill: skill store not initialised. "
            "This is a server-side configuration issue; the user "
            "should restart the application."
        )
        return
    if not isinstance(slug, str) or not slug.strip():
        yield "[tool error] load_skill: 'slug' must be a non-empty string"
        return
    try:
        body = await store.get_body(slug.strip())
    except Exception as e:  # pragma: no cover — defensive
        yield f"[tool error] load_skill failed for '{slug}': {e}"
        return
    if body is None:
        yield f"(skill '{slug}' not found)"
        return
    yield body
