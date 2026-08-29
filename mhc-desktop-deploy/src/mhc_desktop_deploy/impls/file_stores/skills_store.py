"""File-backed skill store.

Layout under ``~/.mhc-desktop/``::

    skills-state.json       # {slug: {enabled, origin, source_path, ...}}
    skills/
      <slug>/
        SKILL.md            # frontmatter + body
        scripts/...         # optional
        references/...      # optional
        assets/...          # optional

``skills-state.json`` keeps user preferences (``enabled``, custom
description, source path) decoupled from the skill folder so that:

* re-importing the same folder does not clobber the user's toggle
* deleting a skill folder does not invalidate saved toggles

This file is small (a few hundred bytes) and re-read on every call.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import shutil
import zipfile
from pathlib import Path
from typing import Any

from mhc_desktop_backend.skills.errors import SkillError
from mhc_desktop_backend.skills.frontmatter import (
    FrontmatterError,
    SkillFrontmatter,
    parse_skill_md,
)
from mhc_desktop_backend.skills.models import Skill, now_iso, safe_join, slugify

logger = logging.getLogger("mhc_desktop_backend")

MAX_SKILL_FILE_BYTES = 1 * 1024 * 1024  # 1 MiB per file
SKILL_FILE_SUFFIXES = {
    ".md",
    ".markdown",
    ".txt",
    ".json",
    ".yaml",
    ".yml",
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".sh",
    ".html",
    ".css",
    ".csv",
    ".toml",
}

class SkillStore:
    """Manage skills on disk.

    All mutating methods take a write lock so concurrent imports of
    the same skill don't corrupt the state file. Reads are lock-free.
    """

    def __init__(
        self,
        skills_dir: Path | None = None,
        state_file: Path | None = None,
    ) -> None:
        from mhc_desktop_deploy.impls.file_stores.paths import (
            SKILLS_DIR,
            SKILLS_STATE_FILE,
        )

        self._dir = skills_dir or SKILLS_DIR
        self._state_file = state_file or SKILLS_STATE_FILE
        self._write_lock = asyncio.Lock()
        self._dir.mkdir(parents=True, exist_ok=True)

    # ── Public API ──────────────────────────────────────────────────

    async def list(self) -> list[Skill]:
        """All installed skills, alphabetically by slug."""
        state = self._load_state()
        out: list[Skill] = []
        for child in sorted(self._dir.iterdir()):
            if not child.is_dir():
                continue
            try:
                skill = await self._read_skill_dir(child, state)
            except Exception:
                logger.exception("failed to read skill dir %s", child)
                continue
            out.append(skill)
        return out

    async def get(self, slug: str) -> Skill | None:
        path = self._dir / slug
        if not path.is_dir():
            return None
        state = self._load_state()
        try:
            return await self._read_skill_dir(path, state)
        except Exception as e:
            raise SkillError(f"failed to read skill '{slug}': {e}") from e

    async def get_body(self, slug: str) -> str | None:
        """Return the markdown body of SKILL.md (no frontmatter)."""
        path = self._dir / slug / "SKILL.md"
        if not path.exists():
            return None
        try:
            fm, body = parse_skill_md(path.read_text("utf-8"))
        except FrontmatterError as e:
            raise SkillError(str(e)) from e
        # If the file had no frontmatter the whole thing is "body"; this
        # matches what the user sees in the editor.
        del fm  # frontmatter isn't part of the body
        return body

    async def get_file(self, slug: str, rel_path: str) -> tuple[str, bytes]:
        path = self._dir / slug
        if not path.is_dir():
            raise SkillError(f"skill '{slug}' not found")
        try:
            abs_path = safe_join(path, rel_path)
        except ValueError as e:
            raise SkillError(str(e)) from e
        if not abs_path.is_file():
            raise SkillError(f"file '{rel_path}' not found in skill '{slug}'")
        if abs_path.stat().st_size > MAX_SKILL_FILE_BYTES:
            raise SkillError(f"file '{rel_path}' is larger than 1 MiB")
        suffix = abs_path.suffix.lower()
        if suffix not in SKILL_FILE_SUFFIXES:
            raise SkillError(f"file type '{suffix}' is not allowed")
        data = abs_path.read_bytes()
        return suffix.lstrip("."), data

    async def install_from_folder(
        self,
        source: Path,
        *,
        origin: str = "imported",
        overwrite: bool = False,
        slug: str | None = None,
    ) -> Skill:
        """Copy a folder containing SKILL.md into the skills dir.

        ``source`` must contain a ``SKILL.md`` file with valid frontmatter.
        The destination slug is taken from the frontmatter name; pass
        ``slug`` to override it (e.g. to let same-named skills from
        different authors coexist under distinct folder names). If that
        already exists and ``overwrite`` is False, a SkillError is raised
        so the caller can decide what to do.
        """
        source = source.resolve()
        if not source.is_dir():
            raise SkillError(f"source '{source}' is not a directory")
        skill_md = source / "SKILL.md"
        if not skill_md.is_file():
            raise SkillError("folder must contain SKILL.md")

        try:
            fm, _body = parse_skill_md(skill_md.read_text("utf-8"))
        except FrontmatterError as e:
            raise SkillError(f"SKILL.md frontmatter error: {e}") from e
        errors = fm.validate()
        if errors:
            raise SkillError("SKILL.md frontmatter is invalid: " + "; ".join(errors))

        target_slug = slug or slugify(fm.name)
        if not target_slug:
            raise SkillError("skill name cannot be empty")
        target = self._dir / target_slug

        async with self._write_lock:
            if target.exists() and not overwrite:
                raise SkillError(f"skill '{target_slug}' already exists")
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source, target)

            state = self._load_state()
            entry = state.setdefault(target_slug, {})
            entry.update(
                {
                    "enabled": entry.get("enabled", True),
                    "origin": origin,
                    "source_path": str(source),
                    "created_at": entry.get("created_at") or now_iso(),
                    "updated_at": now_iso(),
                    "version": fm.version,
                    "license": fm.license,
                }
            )
            self._save_state(state)

        logger.info("installed skill '%s' from %s", target_slug, source)
        return await self.get(target_slug)  # type: ignore[return-value]

    async def delete(self, slug: str) -> None:
        path = self._dir / slug
        async with self._write_lock:
            if path.is_dir():
                shutil.rmtree(path)
            state = self._load_state()
            state.pop(slug, None)
            self._save_state(state)
        logger.info("deleted skill '%s'", slug)

    async def set_enabled(self, slug: str, enabled: bool) -> Skill:
        async with self._write_lock:
            state = self._load_state()
            entry = state.setdefault(slug, {})
            entry["enabled"] = enabled
            entry["updated_at"] = now_iso()
            self._save_state(state)
        skill = await self.get(slug)
        if skill is None:
            raise SkillError(f"skill '{slug}' not found")
        return skill

    async def update_meta(
        self,
        slug: str,
        *,
        description: str | None = None,
        body: str | None = None,
    ) -> Skill:
        """Edit description (frontmatter) and/or body in SKILL.md.

        Body is preserved as-is on the file (just rewritten). Description
        updates both the frontmatter and the state file so the list view
        reflects it without re-parsing every file.
        """
        path = self._dir / slug / "SKILL.md"
        if not path.is_file():
            raise SkillError(f"skill '{slug}' not found")
        text = path.read_text("utf-8")
        try:
            fm, current_body = parse_skill_md(text)
        except FrontmatterError as e:
            raise SkillError(f"SKILL.md parse error: {e}") from e

        new_body = body if body is not None else current_body
        new_desc = description if description is not None else fm.description

        from mhc_desktop_backend.skills.frontmatter import render_skill_md

        new_fm = SkillFrontmatter(
            name=fm.name,
            description=new_desc,
            version=fm.version,
            license=fm.license,
            extra=dict(fm.extra),
        )
        new_text = render_skill_md(new_fm, new_body)

        async with self._write_lock:
            path.write_text(new_text, encoding="utf-8")
            state = self._load_state()
            entry = state.setdefault(slug, {})
            entry["updated_at"] = now_iso()
            entry["description"] = new_desc
            self._save_state(state)
        skill = await self.get(slug)
        if skill is None:
            raise SkillError(f"skill '{slug}' not found")
        return skill

    async def export(self, slug: str) -> bytes:
        """Bundle a skill folder into a portable zip.

        Layout matches Anthropic's portable skill format: the zip
        contains ``<name>/SKILL.md`` plus the rest of the folder
        verbatim so the recipient can extract into their skills dir.
        """
        path = self._dir / slug
        if not path.is_dir():
            raise SkillError(f"skill '{slug}' not found")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in path.rglob("*"):
                if not p.is_file():
                    continue
                rel = p.relative_to(path)
                # Make sure the directory entry exists too so extracting
                # preserves empty folders (e.g. assets/).
                zf.write(p, arcname=f"{slug}/{rel.as_posix()}")
        return buf.getvalue()

    async def import_zip(
        self,
        data: bytes,
        *,
        origin: str = "imported",
        overwrite: bool = False,
        slug: str | None = None,
    ) -> Skill:
        """Install a skill from a zip bundle (export format or downloaded).

        Pass ``slug`` to install under a specific folder name instead of
        the SKILL.md-derived slug (lets same-named skills coexist).
        """
        buf = io.BytesIO(data)
        try:
            with zipfile.ZipFile(buf) as zf:
                names = zf.namelist()
        except zipfile.BadZipFile as e:
            raise SkillError(f"not a valid zip: {e}") from e
        if not names:
            raise SkillError("zip is empty")

        # Detect layout: top-level dir or flat. Anthropic's portable
        # format wraps everything in <slug>/ so we strip that prefix
        # if present.
        prefix = ""
        first_parts = {n.split("/", 1)[0] for n in names if n.strip()}
        if len(first_parts) == 1:
            only = next(iter(first_parts))
            if all(n == only or n.startswith(f"{only}/") for n in names):
                prefix = f"{only}/"
        if not any(n.endswith("SKILL.md") for n in names):
            raise SkillError("zip does not contain SKILL.md")

        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tmp_root = Path(td)
            with zipfile.ZipFile(buf) as zf:
                for name in names:
                    rel = (
                        name[len(prefix) :]
                        if prefix and name.startswith(prefix)
                        else name
                    )
                    if not rel:
                        continue
                    target = safe_join(tmp_root, rel)
                    if name.endswith("/"):
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(name) as src, target.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
            return await self.install_from_folder(
                tmp_root, origin=origin, overwrite=overwrite, slug=slug
            )

    async def content_sha(self, slug: str) -> str:
        """Deterministic content fingerprint: sha256 over each file's
        relative path + bytes, sorted. Never changes with zip metadata
        (timestamps), so it is comparable across devices and with the
        market service's stored ``sha``."""
        path = self._dir / slug
        if not path.is_dir():
            raise SkillError(f"skill '{slug}' not found")
        h = hashlib.sha256()
        for p in sorted(path.rglob("*")):
            if not p.is_file():
                continue
            h.update(p.relative_to(path).as_posix().encode())
            h.update(b"\0")
            h.update(p.read_bytes())
            h.update(b"\0")
        return h.hexdigest()

    async def get_state(self, slug: str) -> dict[str, Any]:
        """Raw state entry for a skill (may be empty if unknown)."""
        return dict(self._load_state().get(slug, {}))

    async def patch_state(self, slug: str, patch: dict[str, Any]) -> None:
        """Shallow-merge ``patch`` into the skill's state entry."""
        async with self._write_lock:
            state = self._load_state()
            entry = state.setdefault(slug, {})
            entry.update(patch)
            self._save_state(state)

    # ── Internal helpers ────────────────────────────────────────────

    async def _read_skill_dir(self, path: Path, state: dict[str, Any]) -> Skill:
        slug = path.name
        skill_md = path / "SKILL.md"
        if not skill_md.is_file():
            raise SkillError(f"skill '{slug}' is missing SKILL.md")
        try:
            fm, body = parse_skill_md(skill_md.read_text("utf-8"))
        except FrontmatterError as e:
            raise SkillError(f"SKILL.md frontmatter error in '{slug}': {e}") from e
        files = sorted(
            str(p.relative_to(path).as_posix())
            for p in path.rglob("*")
            if p.is_file() and p.name != "SKILL.md"
        )
        entry = state.get(slug, {})
        s = Skill(
            slug=slug,
            id=entry.get("id") or "",
            name=fm.name or slug,
            description=fm.description or entry.get("description", ""),
            body=body,
            files=files,
            enabled=bool(entry.get("enabled", True)),
            origin=entry.get("origin", "imported"),
            source_path=entry.get("source_path", ""),
            path=str(path),
            version=fm.version,
            license=fm.license,
            icon=str(fm.extra.get("icon") or ""),
            created_at=entry.get("created_at", ""),
            updated_at=entry.get("updated_at", ""),
        )
        # Backfill the system UUID the first time we see this skill.
        # Persisted to the state file so the next load is stable.
        if not s.id:
            import uuid as _uuid

            s.id = str(_uuid.uuid4())
            entry["id"] = s.id
            self._save_state(state)
        return s

    def _load_state(self) -> dict[str, Any]:
        if not self._state_file.exists():
            return {}
        try:
            return json.loads(self._state_file.read_text("utf-8"))
        except json.JSONDecodeError:
            logger.warning("corrupt %s — ignoring", self._state_file)
            return {}

    def _save_state(self, state: dict[str, Any]) -> None:
        self._state_file.write_text(
            json.dumps(state, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    async def close(self) -> None:
        """No-op — file-backed store has no resources to release.

        Defined so the reference impl satisfies
        :class:`mhc_desktop_backend.protocols.SkillStoreProtocol`.
        """
        return
