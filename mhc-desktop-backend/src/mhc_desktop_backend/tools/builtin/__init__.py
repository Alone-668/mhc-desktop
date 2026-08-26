"""Built-in ``load_skill``: kernel-owned, ``origin="bundled"``.
Seeded enabled on first boot; user's enable/disable choice is
afterwards authoritative (no force re-enable on update).
"""


from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("mhc_desktop_backend")


# Source for the ``load_skill`` built-in tool. Read from the
# kernel directory so the tool source is part of the wheel —
# no extra files to ship, and no environment-dependent paths.
_BUILTIN_LOAD_SKILL_SOURCE = (
    Path(__file__).parent / "load_skill.py"
).read_text(encoding="utf-8")


BUILTIN_LOAD_SKILL = {
    "slug": "load_skill",
    "name": "Load Skill",
    "description": (
        "Load the SKILL.md body of a configured skill. Returns the "
        "raw markdown body for the requested slug. Skills are "
        "listed in the system prompt by name and description; call "
        "this tool when you need the full instructions, references, "
        "or scripts the skill ships with. The ``slug`` is the "
        "directory name under ``~/.mhc-desktop/skills/`` (visible "
        "in the Skills view)."
    ),
    "kind": "local",
    "model_name": "load_skill",
    "parameters": {
        "type": "object",
        "properties": {
            "slug": {
                "type": "string",
                "description": (
                    "The slug of the skill to load, e.g. ``file`` or "
                    "``mhc-investor``. Must match the slug shown in "
                    "the Skills configuration page."
                ),
            }
        },
        "required": ["slug"],
    },
    "origin": "bundled",
    "enabled": True,
}


async def ensure_builtin_tools(app: Any) -> None:
    """Bind the store, populate the local-tool cache, persist the
    source so a uvicorn reload can re-import, and sync the catalog.
    The user's ``enabled`` flag is never touched (no force re-enable).
    """
    skill_store = getattr(app.state, "skill_store", None)
    tool_store = getattr(app.state, "tool_store", None)
    if tool_store is None:
        # No tool store wired (degenerate test app, or older
        # deployment). Nothing we can do — log and move on so the
        # rest of the app boots.
        logger.warning("ensure_builtin_tools: tool_store missing — skipping")
        return

    # 1. Bind the store for the in-process load_skill callable.
    from mhc_desktop_backend.tools.builtin import load_skill as _builtin

    _builtin.set_skill_store(skill_store)

    # 2. Populate the process-local callable cache. ``import_local_tool``
    #    raises ``ValueError`` on a missing ``tool_run`` / ``run`` /
    #    etc. — that would be a kernel-side bug, not a deploy one.
    from mhc_desktop_backend.tools.imports import import_local_tool

    await import_local_tool(BUILTIN_LOAD_SKILL["slug"], _BUILTIN_LOAD_SKILL_SOURCE)

    # 3. Persist the source so future restarts can re-import.
    tools_dir = getattr(tool_store, "_dir", None)
    if tools_dir is not None:
        try:
            dest_dir = Path(tools_dir) / BUILTIN_LOAD_SKILL["slug"]
            dest_dir.mkdir(parents=True, exist_ok=True)
            (dest_dir / "tool.py").write_text(
                _BUILTIN_LOAD_SKILL_SOURCE, encoding="utf-8"
            )
        except OSError:
            # Non-fatal: the in-process cache is enough for the
            # current process. Log so a deployment with a read-
            # only data dir shows up in diagnostics.
            logger.exception(
                "ensure_builtin_tools: failed to persist load_skill.py"
            )

    # 4. Sync the catalog. Re-import on every startup is harmless
    #    but the cheap path is the "already up to date" no-op.
    existing = await tool_store.get(BUILTIN_LOAD_SKILL["slug"])
    if existing is None:
        await tool_store.create(dict(BUILTIN_LOAD_SKILL))
        logger.info("builtin_tools.installed slug=load_skill")
    elif _needs_sync(existing, BUILTIN_LOAD_SKILL):
        await tool_store.update(
            BUILTIN_LOAD_SKILL["slug"], dict(BUILTIN_LOAD_SKILL)
        )
        logger.info("builtin_tools.synced slug=load_skill")


def _needs_sync(existing: Any, builtin: dict[str, Any]) -> bool:
    """Diff on kernel-owned fields only; ``enabled`` is user state."""
    for key in ("name", "description", "parameters", "model_name", "kind", "origin"):
        if getattr(existing, key, None) != builtin.get(key):
            return True
    return False


__all__ = ["BUILTIN_LOAD_SKILL", "ensure_builtin_tools"]
