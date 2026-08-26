# mhc-desktop-frontend

Vue 3 SPA for the mhc-desktop Skill/MCP client.

- Stack: Vue 3 + Pinia + vue-router + Vite (TypeScript)
- Dev port: `5180` (proxies `/api` and `/ready` to backend)

## Routes

| Path | View | Purpose |
| --- | --- | --- |
| `/chat` | `ChatView.vue` | Send messages, stream responses, choose provider/model |
| `/providers` | `ProvidersView.vue` | CRUD providers + pick a preset to seed a new entry |
| `/skills` | `SkillsView.vue` | Import / inspect / toggle Skills |
| `/mcp` | `MCPView.vue` | Import / inspect / toggle MCP servers |
| `/settings` | `SettingsView.vue` | Theme + language + replay the welcome tour |
| `/settings` | `SettingsView.vue` | Theme + language |

## Dev

```bash
npm install
npm run dev
# open http://127.0.0.1:5180
```

Backend URL is controlled by `MHC_BACKEND` (default `http://127.0.0.1:8765`).
Or use the workspace helper:

```bash
bash scripts/dev-mhc-desktop.sh
```

## Build

```bash
npm run build
# output: packages/mhc-desktop-frontend/dist/
```

Consumed by the Electron host (`mhc-desktop-app`) at packaging time. The
build also bakes the bundled fonts into `dist/fonts/`.

## Fonts

The UI ships with the HarmonyOS Sans family bundled as static assets
under `public/fonts/`. The browser loads each weight from
`/fonts/HarmonyOS_Sans[-SC]-<Weight>.ttf`; CJK glyphs are scoped via
`unicode-range` so the browser only fetches the SC family when a CJK
character is on screen.

| File | Size | When it loads |
| --- | --- | --- |
| `HarmonyOS_Sans-Regular.ttf` | 144 KB | preloaded (`<link rel=preload>`) |
| `HarmonyOS_Sans-Medium.ttf`  | 143 KB | on first `font-weight: 500` use |
| `HarmonyOS_Sans-Bold.ttf`    | 143 KB | on first `font-weight: 700` use |
| `HarmonyOS_Sans_SC-Regular.ttf` | 7.9 MB | preloaded, CJK only |
| `HarmonyOS_Sans_SC-Medium.ttf`  | 7.9 MB | CJK + 500 |
| `HarmonyOS_Sans_SC-Bold.ttf`    | 7.8 MB | CJK + 700 |

To add a new weight, drop the TTF in `public/fonts/` and append a
matching `@font-face` block in `src/styles/fonts.css` — no JS
changes.

`scripts/e2e-fonts.mjs` asserts all six rules register and the
Regular weight of both families actually downloads.

## Onboarding overlay

On first run the app opens a three-card overlay fetched from
`GET /api/v1/onboarding`. The dismissal flag lives at
`localStorage["mhc.onboarding.done"]`; reload after dismiss
skips the overlay entirely. Settings → "再次显示欢迎指引"
(Replay tour) clears the flag and re-opens the overlay from
card 0.

The three card types ship with the backend at
`mhc_desktop_backend/api/onboarding.py`:

* `centered`   — text only, big display type, GSAP fade-up
* `media-text` — left/right split with GSAP slide-in (left media ~60%, right text ~40%)
* `media-top`  — top/bottom split (top media ~65%, bottom text ~35%)

The media area carries a real illustration: `media-text` shows
`public/onboarding/skills.svg` (a SKILL.md document with skill
pills attached), `media-top` shows `public/onboarding/mcp.svg`
(a hub-and-spoke diagram with six tool nodes connected to a
central MCP server). Both SVGs ship under `public/` so vite
copies them to `dist/` and they ride along inside the Electron
asar without any extra packaging step.

Adding a fourth type means a new literal in the union on both
ends (Pydantic `Literal` + TypeScript union) and a new branch
in `components/Onboarding.vue`.

### Locale-aware copy

The overlay is fully localised:

* The backend resolves `title` / `body` from the request's
  `Accept-Language` header (`mhc_desktop_backend/api/locale.py`
  parses RFC 7231 tags; defaults to English). It also returns
  the full `title_i18n` / `body_i18n` dicts so the renderer can
  switch languages at runtime without a re-fetch.
* The frontend sends `Accept-Language: <current locale>` on
  every onboarding fetch and picks the localised copy from the
  dicts when the user flips the language in Settings.
* Card text is non-selectable (`user-select: none` on the
  overlay root) so users can't drag-copy walkthrough copy.

`scripts/e2e-onboarding.mjs` drives the live renderer via CDP
and asserts the card sequence, label transitions, image load,
`user-select: none`, dismissal flag, persistence across reload,
`Accept-Language` header, and locale-switch re-render.
## Chat subsystem

The ChatView (`src/views/ChatView.vue`) is built around three
primitives that together deliver the goal's behaviour:

### Markdown rendering
Assistant content is rendered through `components/MarkdownView.vue`,
which wraps `@incremark/vue`. Incremark parses markdown
incrementally — chunks append to the existing parse tree instead
of re-parsing from scratch on every SSE event. The current pending
block is shaded with a soft shimmer animation so the user can
see which line is growing.

### Per-session stream bus
`stores/sessionStreams.ts` owns one EventSource-equivalent per
session. Multiple sessions can stream in parallel; switching to
another session keeps the previous one's bus alive so it can
keep appending chunks. Each session's state — `streaming`,
`assistantContent`, `toolCalls`, `usage`, `cancelled`, `error` —
lives in the bus, not in ChatView, so a switch-back picks up
where it left off.

The bus also debounces session-store writes (1.5 s) and persists
on terminal events. A window close mid-stream loses at most
~1.5 s of content. The Electron host invokes
`window.__mhcFlush()` from its `before-quit` handler to make
sure those writes flush before the backend child dies.

### Tool-call capsules
`components/ToolCallCapsule.vue` renders each MCP tool call as
a horizontal pill under the assistant message. Status colours
match the goal:

| status     | pill                            |
|------------|---------------------------------|
| pending    | gray border, soft flash         |
| executing  | accent-blue border, soft flash  |
| success    | green border                    |
| error      | red border                      |

Click to expand an inline panel showing `args` + `result` +
`error`. `lib/toolUiRegistry.ts` lets code register a custom
Vue component per `<mcp>::<tool>` to take over the detail
panel; anything not registered falls back to the text view.

The backend emits one `tool_call_start` (call_id, name, args)
and one `tool_call_done` (call_id, ok, result, error) per call
so the frontend's state machine flips the pill at the right
moments.

### Context-usage meter
Slim pill on the composer's actions row, hidden until the first
`done` event delivers usage. Two segments: prompt + completion,
sized against the model's `max_context` (per-model field, with
a `max_context_default` fallback on the provider).

### Virtualised list
`components/VirtualMessageList.vue` is a 150-line self-contained
virtualizer that keeps scroll perf flat at 10k messages — only
the visible window of ~20 rows is in the DOM, with spacers above
and below to preserve scroll geometry.

#### ⚠️ Edit-with-care: `heights` must stay a `shallowRef` + `triggerRef`

The per-row measured-height cache is the load-bearing piece for
scroll correctness. It MUST be `shallowRef(new Map<...>())` with
explicit `triggerRef(heights)` after every mutation — NOT a plain
`Map`. The reactivity contract is:

```ts
// right
heights.value.set(id, h)
triggerRef(heights)

// wrong — silent regression, spacers go stale again
heights.set(id, h)
```

The "wrong" version came back as a long-conversation scroll bug
(progress bar sticking / jumping, can't scroll past a point) the
first time the file was written. If you ever see symptoms like
that on long chats, **grep `heights.` first** — if any call site
is missing `triggerRef`, that's the bug. The file's header comment
explains the mechanism.

Code review checklist for this file:
- every `heights.value.set(...)` / `.clear()` is followed by
  `triggerRef(heights)`
- `indexed` / `totalHeight` / `visibleRange` all read
  `heights.value` (not a bare `heights`)
- the scroll-anchor block (`captureAnchor` /
  `restoreAnchor` / `onBeforeUpdate` + `onUpdated` rAF) is intact

#### Scroll anchor

When measurements converge mid-session (code block finishes syntax
highlighting, an image resolves, a streamed chunk grows a row),
spacer geometry changes. Without an anchor the browser clamps
`scrollTop` on shrink and the user's reading position visibly
jumps. The component captures the topmost visible row in
`onBeforeUpdate` and restores it after the next paint via
`requestAnimationFrame`, gated on `heightsChangedInLastMeasure`
so it only fires when spacers actually moved. The restore is a
no-op when the user is at the bottom (ChatView's
`_scrollToBottom` wins).

### Persistence
The frontend persists `tool_calls` on assistant messages; the
chat SSE stream itself never sends the full tool_calls array as
part of a message payload — it emits incremental
`tool_call_start` / `tool_call_done` events and the frontend
accumulates them locally. So an SSE chunk payload is a delta;
the persisted message is a snapshot, exactly as the goal
specifies.

## E2E
`scripts/e2e-chat.mjs` covers all of this in 30 CDP-driven
checks: markdown rendering, tool capsules with status colours
and click-to-expand, custom-UI registry contract, context
meter, parallel-session / switch-back resume, graceful
shutdown via `__mhcFlush`, virtualisation (200 messages in
storage but only the visible window in the DOM), and
tool_calls round-trip via persistence.

## Tools (the third concept — Skill / MCP / Tool)

A "Tool" is an executable unit the LLM can call, parallel to MCP.
Three kinds mirror minimal-harness's binding union:

* **local** — in-process Python async callable (bundled `now` /
  `uuid` ship this way; user-imported scripts via exec'd source
  also land here)
* **script** — external Python file (stub for this build)
* **remote** — SSE-over-HTTP endpoint (stub for this build)

### Sidebar

The left nav now has three foldable workspace sections — Skills,
MCP, Tools — separated by a hairline divider above Tools so the
"下半部分是工具" layout is visually obvious. Each row tints to
match its concept on hover: accent-soft for active skills, green
for MCP, purple for Tools.

### ToolsView

A full management page at `#/tools` parallels MCPView: list of
installed tools with on/off toggles, kind badges, and a Python-
source import form on the right pane. Export downloads a JSON
manifest the user can hand to another machine.

### Capsule UI

`ToolCallCapsule.vue` distinguishes MCP from Tool visually:

| Kind  | Icon  | Kind badge | Success border |
|-------|-------|------------|----------------|
| MCP   | ⚙     | green "MCP"| #16a34a        |
| Tool  | 🔨    | purple "TOOL"| #7c3aed      |
| both  | ✕ error→ red | shared     | #dc2626 |

The `kind` discriminator on every tool SSE event drives this
without the frontend having to parse the namespaced `name` field.

### SSE event vocabulary

Renamed to match minimal-harness: `tool_start` / `tool_progress`
/ `tool_end` (replacing the old `tool_call_start` /
`tool_call_done`), plus `execution_start` / `execution_end` markers
around the batch.

### E2E

`scripts/e2e-tools.mjs` — 21 CDP-driven checks covering import,
toggle, sidebar foldable persistence, capsule distinction, and
the goal's "skill drives mixed MCP+Tool execution" scenario
(persisted as a session with the bundled `mcp-tool-mix` skill
chip plus both capsules in the assistant message).
