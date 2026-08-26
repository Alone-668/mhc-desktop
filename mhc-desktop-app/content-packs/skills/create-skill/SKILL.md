---
name: create-skill
description: Create a new skill (a folder containing SKILL.md plus optional scripts/references/assets) following the schema used by mhc-desktop. Use when the user asks to author, scaffold, draft, or generate a new skill from scratch.
---

When the user wants a new skill, you create a complete, import-ready skill folder and hand back the path. This skill is the rulebook for what that folder must look like.

## Folder layout (mandatory)

```
<slug>/
  SKILL.md          # required — frontmatter + body
  scripts/          # optional — Python or shell helpers
  references/       # optional — markdown / docs the model can read
  assets/           # optional — images, data files
```

`<slug>` must be the directory name. The runtime reads the folder by its slug, so the slug and the frontmatter `name` should agree.

## SKILL.md frontmatter (required)

YAML between two `---` lines at the very top of the file:

```yaml
---
name: <slug>                            # required — must match directory name
description: <one or two sentences>     # required — what triggers this skill
version: 0.1.0                          # optional
license: MIT                             # optional
---
```

### Field rules

- `name`: lowercase ASCII letters, digits, and hyphens. Must start and end with a letter or digit. No consecutive hyphens. The slug the runtime derives from `name` is the import directory name.
- `description`: free text, but treat it as the "when to use" trigger phrase. The user reads this in the management list and the model uses it to decide when to attach the skill. Be specific. "Reviews PR diffs and flags bugs" beats "helps with code".
- `version`, `license`: optional. Both appear in `~/.mhc-desktop/skills-state.json` and the API response.

## SKILL.md body (required)

Markdown after the frontmatter closing `---`. This is what actually gets sent to the model when the skill is attached to a chat, so:

- Write it as instructions **to the model**, not as documentation **to the user**. Imperative voice. "When the user gives you a file path, read it with the `read_file` tool" — not "the user can read files".
- Open with a one-line statement of what this skill makes the model do differently.
- Use `##` and `###` headings for sections. Avoid emoji.
- Examples are gold — include 1-3 concrete input/output pairs the model can pattern-match on.
- If the skill needs the model to call a tool, name the tool exactly (`read_file`, `now`, etc.) and explain what to pass.
- Keep it tight. If a paragraph doesn't change the model's behaviour, delete it.

## Optional companion files

- `scripts/` — Python or shell scripts the skill body can tell the model to run. Put a one-line docstring at the top of every script explaining what it does and what its arguments are.
- `references/` — Markdown reference docs. Reference them by relative path from the SKILL.md body (`See [Schema](references/schema.md)`).
- `assets/` — anything binary. Reference them by relative path.

## Pre-flight checklist before handing back the skill

1. Open the SKILL.md you just wrote and confirm:
   - YAML frontmatter parses (no tabs, no `:` without a space, no orphan `---`)
   - `name` matches the directory name and obeys the slug rules
   - `description` is concrete and trigger-shaped
   - Body opens with a one-line "what this skill does" statement
2. If you wrote any `scripts/` files, confirm each one runs with `python scripts/<name>.py --help` (or equivalent).
3. If you referenced any companion file, confirm the relative path exists from the SKILL.md.
4. The skill folder lives somewhere the user can point a folder picker at. Hand them the absolute path.

## Delivery format

Reply with:

1. The absolute path to the new skill folder.
2. A one-paragraph summary of what the skill does and when the model should attach it.
3. Any companion files you created, with their purposes.
4. Suggested next step — usually "import via Skills → Import pack (folder)…, or zip the parent folder and use Import pack (zip)…".

Do not paste the SKILL.md body inline unless the user asks; the file is the artifact.