# Adding Built-in Skills, Tools, and MCPs

Workflow for shipping default content that ships **inside the mhc-desktop
installer** and is auto-materialized on every fresh install. If you only
need content for one user, use the management page's
"Import pack (zip)…" button instead — that's the
`<resourcesPath>`-less, single-user path.

This doc covers the full lifecycle: **schema → dev iteration →
rebuild → ship → user upgrade behavior → troubleshooting**.

Companion docs:

- [`packages/mhc-desktop-app/content-packs/README.md`](../packages/mhc-desktop-app/content-packs/README.md) —
  the directory layout, slug rules, per-domain schema reference
- [`docs/PACKAGING-MHC-DESKTOP.md` §3.6](PACKAGING-MHC-DESKTOP.md#36-打包阶段把-content-packs-一起-ship--后端-lifespan-启动时-materialize) —
  the build pipeline that wires content-packs into the installer

---

## When to use this

| You want to … | Use this workflow? |
| | |
| Ship a starter skill/tool/MCP that every fresh install sees | ✅ yes |
| Iterate on an existing bundled skill/tool/MCP's body | ✅ yes (dev shortcut at the bottom) |
| Add content for **one user only** | ❌ use `import-bulk` (zip upload) |
| Update an already-installed skill's body for a single user | ❌ use the Settings page |

---

## Decision tree: skill vs tool vs MCP

| | What the model can do with it | Where the executable lives | Author effort |
|---|---|---|---|
| **Skill** | Reads a markdown body + optional `references/` files via `read_file` during a chat | In the model context — no separate runtime | Lowest: just write `SKILL.md` |
| **Tool** | Calls `tool_run(**kwargs)` mid-conversation and streams the result | Embedded in the backend process (`local` kind) or a separate subprocess | Low: write Python + 5-line manifest |
| **MCP** | Spawns an external MCP server process and bridges its tools | A separate subprocess started via `command + args` | Medium: needs a working MCP server (npx / docker / binary) |

A skill is for **telling the model what it can do**. A tool is for **doing it
itself in-process**. An MCP is for **talking to an external service that
already speaks MCP**.

---

## Conventions shared across all three domains

### Slug rules

- Lower-case ASCII letters, digits, hyphens.
- ≤ 64 characters.
- **Slug = directory name** under the matching `skills/` / `tools/` /
  `mcp/` subdir. Reusing a slug that already exists in the user's
  `~/.mhc-desktop/` triggers the "skip-if-exists" rule below.
- Frontmatter `name` / manifest `name` / config `name` should match
  the slug (other capitalizations are tolerated but cosmetically ugly).

### `origin` field

When the bundled content is materialized into the user's store, each
unit's `origin` is recorded as `"bundled"`. The renderer surfaces this
in the management pages so you can tell apart bundled defaults from
units the user added manually. Don't change it — the materialize
helper sets it.

### Storage layout (what ships in the installer)

```
packages/mhc-desktop-app/content-packs/
├── README.md
├── skills/<slug>/SKILL.md (+ optional references/, scripts/, assets/)
├── tools/<slug>/tool.py (+ optional manifest.json)
└── mcp/<slug>/config.json
```

electron-builder's `extraResources` block in
`packages/mhc-desktop-app/package.json` stages this whole tree at
`<resourcesPath>/content-packs/`. On first launch the backend's
`materialize_bundled()` walks that tree and installs each unit.

---

## Adding a skill

### File layout

```
content-packs/skills/<slug>/
├── SKILL.md          ← required
├── references/       ← optional, recursive .md / .json / .py files
├── scripts/          ← optional, code the skill body mentions
└── assets/           ← optional, images / data the model can read
```

### `SKILL.md` schema

```markdown
---
name: my-skill               # required, lowercase ASCII + hyphens
description: >               # required, shown to the LLM verbatim
  One-paragraph description
  of what this skill enables.
version: 0.1.0               # optional but recommended
license: MIT                 # optional
---

# My Skill

Body the model reads when this skill is enabled. Markdown.
Reference relative paths with `references/foo.md` and the model can
read them via the standard file-read tool.
```

The `name:` field is the authoritative slug source; the directory
name is just the staging label. If they disagree the frontmatter
wins.

### Dev iteration (without rebuilding the installer)

1. Edit `content-packs/skills/<slug>/SKILL.md` in the repo.
2. From the running app's **Skills** page: delete the existing
   `<slug>` (it's marked `origin: bundled`).
3. Click **Import pack (zip)…** → pick
   `packages/mhc-desktop-app/content-packs/skills/` (or a hand-zipped
   `<slug>/`).
4. The body lands in `~/.mhc-desktop/skills/<slug>/` immediately;
   refresh the page to see it.

### Ship

Re-run the full build pipeline (`build-spa` → `build-bundled-python`
→ `npm run build` → `electron-builder`). The new SKILL.md is captured
in `win-unpacked/resources/content-packs/skills/<slug>/` automatically;
no other config changes.

---

## Adding a tool

### File layout

```
content-packs/tools/<slug>/
├── tool.py          ← required
└── manifest.json    ← optional but recommended
```

### `tool.py` schema

```python
# async def tool_run(**kwargs) is the entry point. Yield strings;
# the model streams the concatenation.

async def tool_run(cmd: str, *args: str) -> str:
    """Run a shell command and stream stdout."""
    proc = await asyncio.create_subprocess_shell(
        f"{cmd} {' '.join(args)}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    async for chunk in proc.stdout:           # type: ignore[union-attr]
        yield chunk.decode("utf-8", errors="replace")
    rc = await proc.wait()
    if rc != 0:
        yield f"\n[exit code {rc}]"
```

The runtime imports `tool_run` from the module on demand. Other public
functions are ignored.

### `manifest.json` schema

```json
{
  "name": "Pretty Tool Name",
  "description": "One-paragraph description shown to the LLM",
  "parameters": {
    "type": "object",
    "properties": {
      "cmd":   { "type": "string" },
      "args":  { "type": "array", "items": { "type": "string" } }
    },
    "required": ["cmd"]
  },
  "version": "0.1.0",
  "license": "MIT"
}
```

Without `manifest.json`, the tool gets a generic name (from the
directory) and an empty parameter schema — the model sees it but
doesn't know how to call it. Always ship a manifest.

### Dev iteration

Same as skills: edit `tool.py` / `manifest.json` in the repo, then
from the running app's **Tools** page delete the old tool and
re-import the folder.

A Python syntax error in `tool.py` surfaces as
`summary.errors[N].error` in `mhc-desktop.log` under
`content_packs.tools errors=N`. The runtime skips that unit but
keeps installing the others.

### Ship

Re-run the build pipeline. Tools don't go through the Python wheel — they
ship directly under `win-unpacked/resources/content-packs/tools/`. The
`extraResources` filter excludes `__pycache__/` so it stays clean.

---

## Adding an MCP

### File layout

```
content-packs/mcp/<slug>/
└── config.json      ← required
```

### `config.json` schema

```json
{
  "name": "filesystem",
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
  "description": "Read/write under /tmp",
  "env": {}
}
```

`command + args` are passed verbatim to `subprocess.Popen`. `env`
is added to the parent process environment. **Test the spawn locally
first** — a bad `command`/`args` crashes the spawn with no useful
error in the bundled path. Run the same `command + args` in a shell
and confirm the server prints an MCP hello on stdout.

### Dev iteration

Same pattern: edit `config.json`, delete the old MCP from the
management page, re-import. The `refresh_tools` button on the MCP
page forces the manager to re-discover the server's tool list.

### Ship

Re-run the build pipeline. MCP configs ship under
`win-unpacked/resources/content-packs/mcp/`.

---

## Workflow: drop → dev-test → rebuild → ship

```
1. Author                Drop the file(s) into content-packs/{skills,tools,mcp}/<slug>/
2. Validate locally      uv run pytest packages/mhc-desktop-backend/tests/test_content_packs.py -v
                         (write a unit test that mirrors your SKILL.md / tool.py / config.json
                         against the bulk_install_* helpers if you want CI to catch regressions)
3. Dev-iterate           Restart the backend with MHC_FORCE_UV=uv, edit files in place,
                         reload via the management page's "Import pack (zip)…" button
4. Rebuild               powershell scripts/build-spa.ps1
                         powershell scripts/build-bundled-python.ps1
                         cd packages/mhc-desktop-app && npm run build
                         npx electron-builder --win --x64 --publish never
5. Verify                ls packages/mhc-desktop-app/dist/win-unpacked/resources/content-packs/
                         (must contain <slug>/ — see step 4 in docs/PACKAGING-MHC-DESKTOP.md §7)
6. Ship                  Distribute the new .exe; existing users upgrade; new users
                         get the unit on first boot.
```

**Don't skip step 2**. `bulk_install_*` catches frontmatter errors,
syntax errors, and JSON errors and reports them in `summary.errors[]`,
not in stdout — you'd only see them in `mhc-desktop.log` after the
next user launch. A test in `test_content_packs.py` against your
specific files catches the problem on your machine.

---

## Updating existing bundled content

`materialize_bundled()` defaults to `overwrite=False`. This is a
principled choice: **user customizations win over bundled defaults**.
Here's how that plays out:

| Edit shape | What existing users see | What new users see |
|---|---|---|
| **New unit** (`new-skill/` added to v0.2.0) | Materialized on upgrade | Materialized on first boot |
| **Existing unit, content unchanged** | Nothing — materialize skips it | Materialized on first boot |
| **Existing unit, content changed** (`SKILL.md` rewritten for v0.2.0) | **Stale — they still have v0.1.0's body** | Get v0.2.0's body on first boot |
| **Existing unit, deleted from content-packs** | Still in their `~/.mhc-desktop/` — manual cleanup | N/A |

### Pushing an update to existing users

For the third row above (revised body), pick one:

1. **Don't push** — the existing user keeps their copy. Most bundles
   ship non-breaking additions this way.
2. **Ask the user to re-import** — ship a v0.2.0.zip alongside the
   installer; the user opens the management page, clicks "Import
   pack (zip)…", picks the zip. The route handler respects
   `overwrite=true` per request. This is the only on-by-default path
   for forcing a refresh.
4. **Force the materialize call to overwrite=true** — change
   `app.py`'s `materialize_bundled(...)` invocation. ⚠️ This nukes
   user edits on every launch. Don't ship this unless you have a
   strong reason.

### Slug collision

Two units with the same slug (e.g. one bundled, one imported) on the
same install: the bundled one wins because materialize runs first.
The imported one's slug will report `summary.errors[]` or be
rejected on the import-bulk path.

---

## Troubleshooting

### "I added the file, rebuilt, but the user doesn't see it"

| Symptom | Likely cause | Where to look |
|---|---|---|
| File not in `win-unpacked/resources/content-packs/` | Didn't run `electron-builder` after `build-spa` and `build-bundled-python` | Rebuild from scratch |
| File present but `mhc-desktop.log` shows `content_packs.skills skipped=N` | User has the slug already (probably from a prior version) | Tell user to delete `~/.mhc-desktop/skills/<slug>/` and restart |
| File present but log shows `content_packs.skills errors=N` | Bad frontmatter / syntax / JSON | Check `summary.errors[i].path` and `summary.errors[i].error` in the log |
| Manifest missing → tool appears but LLM can't call it | Wrote `tool.py` without `manifest.json` | Add `manifest.json`; the parameter schema is what teaches the LLM |
| `name:` field in SKILL.md differs from directory name | Frontmatter wins, directory is just a label | Match them to avoid confusion |

### Reading the log

```
mhc-desktop.log:
  [INFO] content_packs.skills installed=2 skipped=1 errors=0
  [INFO] content_packs.tools  installed=1 skipped=0 errors=1
  [INFO] content_packs.mcp    installed=1 skipped=0 errors=0
```

- `installed>0` for a domain → that domain materialized something
- `skipped>0` → at least one one of already existed; the user kept their copy
- `errors>0` → look at the next INFO line where each error's
  `path` and `error` is logged at DEBUG level

For a per-error breakdown, set `MH_LOG_LEVEL=DEBUG` in the spawned
backend env (rebuild and ship a debug build, or temporarily set the
env in main.ts during development).

### Frontmatter gotchas

- The `name:` field must be a valid slug (lowercase ASCII + hyphens).
  Uppercase letters get lowercased silently.
- A missing closing `---` is a parse error → reported as
  "frontmatter error in '...': unterminated frontmatter block".
- Unknown frontmatter fields are tolerated (kept under
  `frontmatter.extra`) — feel free to add metadata fields for your
  own documentation.

### Tool gotchas

- `async def tool_run(**kwargs)` — the name and async-ness are
  non-negotiable; missing either → "import_local_tool" error.
- The function MUST `yield` at least once. `return "..."` works too
  (it's coerced to a single-yield), but mixing return + yield
  confuses the runner.
- The runner captures `BaseException` — your tool should fail loudly
  (raise) rather than swallow.

### MCP gotchas

- The `command` must be on PATH or be an absolute path. If the
  spawn fails, the MCP appears in the management page but
  `refresh_tools` returns an empty list and the chat handler
  reports "tool error: no callable loaded" on the first call.
- A bad `args` element crashes the spawn — validate the schema
  matches what the server expects (most `@modelcontextprotocol/*`
  servers expect `-y <package>` for `npx` and `--rm -i ...` for
  `docker`).
- `env` is shallow-merged with the parent process env. Don't
  override `PATH` unless you mean it.

---

## Where the code lives

| Concern | File |
|---|---|
| Per-domain bulk install (skills/tools/mcps) | `packages/mhc-desktop-backend/src/mhc_desktop_backend/content_packs.py` |
| HTTP routes that share the helpers | `packages/mhc-desktop-backend/src/mhc_desktop_backend/api/{skills,tools,mcp}.py` |
| Lifespan startup invocation | `packages/mhc-desktop-backend/src/mhc_desktop_backend/app.py` (`materialize_bundled` in the lifespan) |
| `process.resourcesPath` → `MHC_RESOURCES_PATH` env | `packages/mhc-desktop-app/src/main.ts` |
| `extraResources` config | `packages/mhc-desktop-app/package.json` |
| Build pipeline | `scripts/build-spa.ps1`, `scripts/build-bundled-python.ps1`, `electron-builder` invocation |
| Tests pinning the invariants | `packages/mhc-desktop-backend/tests/test_content_packs.py` |

The three invariants the test suite locks (and that this doc must
respect):

1. **Idempotent boot**: launching the same installer twice doesn't
   duplicate. (`test_materialize_bundled_is_idempotent`)
2. **User customizations preserved**: a skill edited by the user
   survives the next launch. (`test_materialize_bundled_preserves_user_edits`)
3. **Bad unit doesn't poison the batch**: a malformed
   `tool.py` is reported, not crashed on. (`test_bulk_install_tools_broken_tool_records_error`)

If you add a new domain (e.g. "prompts") to the content packs, mirror
the existing pattern: one `bulk_install_<domain>` helper, one fixture
in tests, one route handler that shares the helper, one
`materialize_bundled` orchestration call.