# content-packs

Default content shipped alongside the mhc-desktop installer.

> **Authoring / workflow docs** — the full lifecycle (drop → dev-test →
> rebuild → ship → user upgrade behaviour → troubleshooting) lives in
> [`docs/BUILTIN-CONTENT.md`](../../../docs/BUILTIN-CONTENT.md). This
> README is the directory-layout reference.

The installer ships a **bundled starter set** that auto-materializes on
first boot: skills / MCPs / tools under
``skills/``, ``mcp/``, ``tools/`` here are installed into
``~/.mhc-desktop/{skills,mcp,tools}/`` the first time the backend starts
from the packaged app. On subsequent launches the materialize step is a
no-op for units already present, so user customizations (edited bodies,
disabled flags, custom configs) are preserved.

In dev mode the auto-materialization is a no-op entirely — the bundled
content is sourced from the repo as-is, so importing it through the
"Import pack (zip)…" management page lets us iterate on skill bodies
without rebuilding the installer.

This directory is the **source of truth** for both:

* the units that ship with the installer (electron-builder
  ``extraResources`` copies the whole tree to ``<resourcesPath>/
  content-packs/`` at build time, see
  ``docs/PACKAGING-MHC-DESKTOP.md`` §3.6), and
* separate zip artifacts customers import manually on top of the bundled
  set.

```
content-packs/
  README.md             (this file)
  skills/
    <slug>/
      SKILL.md
      references/...
  mcp/
    <slug>/
      config.json
  tools/
    <slug>/
      tool.py
      manifest.json     (optional)
```

Each immediate child folder of `skills/`, `mcp/`, or `tools/` is one
shippable unit. A folder is also a valid bulk-import target as-is.

## Packaging a content pack

Pick one unit and zip its parent + unit together. From the repo root:

```bash
# A single skill pack:
cd packages/mhc-desktop-app/content-packs/skills
zip -r create-skill-0.1.0.zip create-skill/

# A multi-skill bundle (parent contains many skills):
cd packages/mhc-desktop-app/content-packs
zip -r skills-pack-0.1.0.zip skills/

# A full content pack (skills + MCPs + tools):
cd packages/mhc-desktop-app
zip -r content-pack-0.1.0.zip content-packs/
```

The customer imports the resulting file via **Skills / MCP / Tools →
Import pack (zip)…** in the running app. The backend extracts and copies
each unit into `~/.mhc-desktop/<thing>/<slug>/`; the source zip is left
untouched.

## Conventions

- **Slugs must be lowercase ASCII letters, digits, and hyphens**. The
  slug is the directory name and must match the `name:` field in
  `SKILL.md` / `config.json` / `tool.py`.
- **Version in the directory name** for releases — e.g. `create-skill-0.2.0/`
  — so we can keep old versions in the repo without colliding with
  newer ones. (The runtime only sees the slug after `name:`.)
- **Manifest** for tools: optional `manifest.json` next to `tool.py`
  declaring `name`, `description`, `parameters`. Without it, the tool
  is registered with a generic name and an empty parameter schema.
- **No `__pycache__` or `.pyc` files** — the runtime re-imports the
  Python source on every install; byte-compiled artifacts just confuse
  the tracebacks.

## Adding a new content pack

1. Create the unit folder under the matching `skills/`, `mcp/`, or
   `tools/` directory.
2. Write `SKILL.md` (skills) or `config.json` (MCPs) or `tool.py`
   (tools).
3. Optional but recommended: add a `references/` directory under a
   skill with deeper docs the model can `read_file` when the skill
   is attached.
4. Validate locally — see `scripts/dev-content-pack.sh` (TBD) for a
   one-shot bulk-import + smoke test against a local backend.

## Authoring skill bodies

For a complete reference on the SKILL.md schema (frontmatter rules,
field validation, naming examples, optional companion files), see
[`skills/create-skill/`](skills/create-skill/SKILL.md) — it's the
"skill for creating skills" template that's also itself a valid skill
suitable for shipping to customers who author their own.

## Authoring tools

A tool folder contains ``tool.py`` (Python source defining
``async def tool_run(**kwargs):`` that yields strings) and optionally
``manifest.json`` next to it:

:

```json
{
  "name": "Pretty Name",
  "description": "Short description surfaced to the LLM",
  "parameters": {
    "type": "object",
    "properties": {
      "cmd": { "type": "string" }
    },
    "required": ["cmd"]
  },
  "version": "0.1.0",
  "license": "MIT"
}
```

The slug is the directory name and must match ``name`` in the manifest
(matched case-insensitively for slug purposes — lowercased, hyphens
substituted for non-alphanumerics).

## Authoring MCPs

A MCP folder contains ``config.json``:

:

```json
{
  "name": "filesystem",
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
  "description": "Read/write under /tmp",
  "env": {}
}
```

``command`` + ``args`` are passed verbatim to ``subprocess.Popen``;
``env`` is added to the parent process env. The slug is the directory
name.

## When the bundled unit already exists on the user's machine

The materialize helper skips units whose slug is already in the user
data store, so a power user who has already configured a ``create-skill``
skill will keep their customizations. To push a content update that
forces a re-install, delete the corresponding folder under
``~/.mhc-desktop/{skills,mcp,tools}/<slug>/`` and restart — the next
launch re-materializes from the bundled copy.

We do **not** silently overwrite bundled units: the bundled copy is
the "shipped default" and the user's copy wins unless they explicitly
delete it. This matches the convention used by VS Code extensions and
most auto-update systems.