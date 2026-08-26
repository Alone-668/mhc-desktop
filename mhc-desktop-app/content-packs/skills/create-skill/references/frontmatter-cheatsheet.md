# SKILL.md frontmatter cheat sheet

This is the canonical schema mhc-desktop validates against when it imports a skill. Copy from here when authoring a new one.

## Required fields

| Field | Type | Rule |
|---|---|---|
| `name` | string | Lowercase ASCII letters, digits, hyphens. Must start and end with a letter or digit. No consecutive hyphens. Length ≤ 64. The runtime slugifies this to pick the import directory name. |
| `description` | string | Free text. The runtime stores it verbatim in the skills-state.json and shows it in the Skills management page. The model uses it as the "when to use" trigger phrase. Keep it specific. |

## Optional fields

| Field | Type | Rule |
|---|---|---|
| `version` | string | Semver or any short tag. Stored verbatim. |
| `license` | string | SPDX identifier or free text. Stored verbatim. |

## Naming examples

| name | OK? | Why |
|---|---|---|
| `code-review` | ✅ | Letters and a hyphen, no consecutive hyphens, starts/ends with letter |
| `summarize` | ✅ | All letters |
| `mcp-tool-mix` | ✅ | Letters and hyphens, no consecutive |
| `code--review` | ❌ | Two consecutive hyphens |
| `-review` | ❌ | Starts with hyphen |
| `review-` | ❌ | Ends with hyphen |
| `CodeReview` | ❌ | Uppercase letters |
| `代码_review` | ❌ | Non-ASCII / underscore |

## Full template

```markdown
---
name: your-slug-here
description: One or two sentences explaining when the model should use this skill.
version: 0.1.0
license: MIT
---

# What this skill does

One-line statement of the behaviour this skill gives the model. Imperative voice.

## How to apply it

The instructions the model should follow when this skill is attached. Write them as
"do X, then Y" — not as "the user can do X".

## Examples

### Input

… what the user might say …

### Output

… what the model should produce …

## Companion files

- `scripts/example.py` — does X. Run with `python scripts/example.py`.
- `references/spec.md` — detailed reference, link from the body if needed.
```

## Validation

The backend rejects a skill with:

- Missing `name` or `description` in frontmatter
- `name` that fails the slug rules above
- SKILL.md missing from the folder

A failed import returns a 400 with the exact reason; the file is not copied to `~/.mhc-desktop/skills/<slug>/` in that case.

## Where the skill ends up

After a successful import:

```
~/.mhc-desktop/
  skills-state.json              # {slug: {enabled, origin, source_path, ...}}
  skills/
    <slug>/
      SKILL.md                   # verbatim copy of the source
      scripts/...                # verbatim copies
      references/...             # verbatim copies
      assets/...                 # verbatim copies
```

The original folder you imported from is **not modified**. The runtime only ever reads from the copy under `~/.mhc-desktop/skills/`.