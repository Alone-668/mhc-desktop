<!--

  Themed code-block component for MarkdownView.

  Why this exists
  ---------------

  Incremark (``<Incremark>`` / ``<IncremarkCode>``) ships with a
  single Shiki theme — ``github-dark`` — and there is no prop on
  ``<Incremark>`` to swap it. That hardcoded theme emits light-pastel
  token colors designed for a dark background; if we leave it as-is
  on the app's light page, the tokens are unreadable. We used to
  paper over this with a CSS ``invert + hue-rotate`` filter, but
  that produced washed-out pastels that still looked wrong.

  This component replaces the default code-block renderer with one
  that picks the right Shiki theme for the current app theme:

    * light app → ``github-light``  → dark text on a near-white
      background, matches the page rhythm.
    * dark  app → ``github-dark``   → light text on a near-black
      background, matches the page rhythm.

  We mirror IncremarkCodeDefault's wrapper HTML (``.incremark-code``
  / ``.code-header`` / ``.code-content`` / ``.shiki-wrapper``) so
  the existing styles in ``MarkdownView.vue`` keep applying without
  any duplication.

  Streaming
  ---------

  Incremark dispatches the code block with ``blockStatus="pending"``
  while the model is still emitting tokens and ``"completed"`` once
  the fence is closed. IncremarkCodeDefault handles both states by
  re-highlighting on every delta (because new tokens change the
  token boundaries). Our component does the same — debounced via
  the ``highlight`` watcher — so the streaming UX feels identical
  to the built-in path, and the final render is on the right theme
  instead of the wrong one.

  Why we manage our own Shiki singleton
  -------------------------------------

  ``@incremark/vue`` keeps a private highlighter keyed by theme
  (``useShiki``); we can't read it, so we make our own. We load
  the two themes we'll need up front, then load languages lazily
  on first use. The highlighter is a process singleton so the
  first `````python`` block doesn't pay the full bundle cost on
  every code block.

  Why ``github-light`` / ``github-dark`` (not ``github-light-high-contrast``)
  -------------------------------------------------------------------------

  These are the two themes ``@incremark/vue`` already trusts (the
  dark variant is its default), so we know they're bundled by
  Shiki 3.x and render identically regardless of the host
  environment. Picking the well-known pair avoids any "missing
  theme" surprises.

  Why we ignore the ``theme`` / ``fallbackTheme`` props
  ----------------------------------------------------

  ``IncremarkCode`` always passes its own ``theme: "github-dark"``
  down to ``defaultCodeComponent``. We ignore that prop entirely
  and let ``useThemeStore`` drive the choice. The unused props
  stay in the signature so ``IncremarkCode``'s render keeps
  type-checking.

-->

<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue"
import {
  createHighlighter,
  type BundledLanguage,
  type BundledTheme,
  type HighlighterGeneric,
} from "shiki"
import { useThemeStore } from "../stores/theme"

interface CodeNode {
  type: "code"
  lang?: string
  value: string
  /** Optional position from the AST — Incremark passes these through. */
  position?: unknown
}

const props = withDefaults(
  defineProps<{
    node: CodeNode
    theme?: string
    fallbackTheme?: string
    disableHighlight?: boolean
    blockStatus?: "pending" | "completed"
  }>(),
  {
    theme: "",
    fallbackTheme: "",
    disableHighlight: false,
    blockStatus: "completed",
  },
)

const themeStore = useThemeStore()

/** Which Shiki theme to ask for. The choice is per-app-theme so
 *  the rendered colors land on the surface they're designed for. */
const shikiTheme = computed<BundledTheme>(() =>
  themeStore.theme === "dark" ? "github-dark" : "github-light",
)

/** Display label in the header bar — Shiki aliases its language
 *  IDs (e.g. ``shellscript``), so we map the common ones back to
 *  what the model actually wrote. */
const language = computed(() => {
  const raw = (props.node.lang || "text").toLowerCase()
  const alias: Record<string, string> = {
    py: "python",
    js: "javascript",
    ts: "typescript",
    sh: "bash",
    shell: "bash",
    zsh: "bash",
    bash: "bash",
    shellscript: "bash",
    yml: "yaml",
    md: "markdown",
    "c++": "cpp",
    "objective-c": "objectivec",
  }
  return alias[raw] ?? raw
})

const html = ref<string>("")
const copied = ref(false)

/** Process-wide Shiki singleton. Loaded lazily — Incremark's
 *  built-in path already pays the cold-start cost once, and we
 *  piggyback on it: the user already saw Shiki load by the time
 *  the first code block streams in. */
let _highlighter: HighlighterGeneric<
  BundledLanguage,
  BundledTheme
> | null = null
let _highlighterPromise: Promise<HighlighterGeneric<
  BundledLanguage,
  BundledTheme
>> | null = null
const _loadedLanguages = new Set<BundledLanguage>()
const _inflight = new Set<BundledLanguage>()

async function _ensureHighlighter() {
  if (_highlighter) return _highlighter
  // Cache the in-flight promise so concurrent callers (a streaming
  // reply with several `` ```python`` blocks re-renders each on
  // every chunk) all await the same ``createHighlighter`` and end
  // up holding the same instance. Without this guard, each
  // concurrent watcher raced to construct its own highlighter,
  // and only the last one to resolve survived — its sibling
  // loadLanguage() calls silently dropped their language because
  // they were operating on an instance that was about to be
  // discarded.
  if (!_highlighterPromise) {
    _highlighterPromise = createHighlighter({
      themes: ["github-dark", "github-light"],
      langs: ["text"],
    }).then((h) => {
      _highlighter = h
      return h
    })
  }
  return _highlighterPromise
}

async function _loadLanguageIfNeeded(lang: BundledLanguage) {
  if (_loadedLanguages.has(lang)) return
  // Serialize concurrent loads for the same language via a per-lang
  // promise cache. Without this, three watchers firing at once for
  // the same ``javascript`` block each issued their own
  // ``loadLanguage`` call; only the last one actually registered
  // the grammar and the others' ``codeToHtml`` calls landed before
  // the singleton highlighter finished loading. ``_inflight`` keeps
  // the early-out for the most common case (a re-render that races
  // against an in-flight load) — ``_loadPromises`` is what makes
  // that early-out actually wait for the load to land.
  if (!_loadPromises.has(lang)) {
    _loadPromises.set(lang, _doLoadLanguage(lang))
  }
  await _loadPromises.get(lang)!
}

const _loadPromises = new Map<BundledLanguage, Promise<void>>()

async function _doLoadLanguage(lang: BundledLanguage) {
  try {
    await _highlighter!.loadLanguage(lang)
    _loadedLanguages.add(lang)
  } catch {
    /* language not supported by this Shiki build — leave it unloaded
       so the watcher falls back to a plain <pre> below */
  }
}

/** Escape characters that would otherwise break inside the raw
 *  HTML string we hand to ``v-html``. Used for the plain-text
 *  fallback when Shiki can't highlight the language. */
function _escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
}

/** Re-highlight whenever the code, the language, or the app theme
 *  changes. Streaming fires this on every chunk — Shiki is fast
 *  enough that the cost is invisible at human-typing speeds. */
async function _highlight() {
  const code = props.node.value ?? ""
  const lang = (language.value || "text") as BundledLanguage

  // Plain-text fallback: skip Shiki entirely. We render <pre><code>
  // so the surrounding CSS keeps applying (the same wrapper
  // classes as Shiki output).
  const langKey = lang as string
  if (props.disableHighlight || langKey === "text" || !code) {
    html.value = `<pre class="shiki"><code>${_escapeHtml(code)}</code></pre>`
    return
  }

  try {
    const hl = await _ensureHighlighter()
    await _loadLanguageIfNeeded(lang)
    if (_loadedLanguages.has(lang)) {
      html.value = hl.codeToHtml(code, { lang, theme: shikiTheme.value })
      return
    }
  } catch {
    /* fall through to plain-text */
  }
  html.value = `<pre class="shiki"><code>${_escapeHtml(code)}</code></pre>`
}

watch(
  () => [props.node.value, props.node.lang, shikiTheme.value, props.disableHighlight],
  _highlight,
  { immediate: true },
)

onMounted(() => {
  // Kick off the singleton load on mount so the first highlight
  // call doesn't pay the cold-start tax mid-stream.
  void _ensureHighlighter()
})

/** Copy the raw code (not the highlighted HTML) to the clipboard.
 *  Visually mirrors IncremarkCodeDefault's copy button. */
async function _copyCode() {
  try {
    if (typeof navigator === "undefined" || !navigator.clipboard) return
    await navigator.clipboard.writeText(props.node.value ?? "")
    copied.value = true
    window.setTimeout(() => {
      copied.value = false
    }, 2000)
  } catch {
    /* clipboard unavailable in this context — silently no-op */
  }
}
</script>

<template>
  <div class="incremark-code">
    <div class="code-header">
      <span class="language">{{ language }}</span>
      <button
        class="code-btn"
        type="button"
        :aria-label="copied ? 'copied' : 'copy code'"
        :title="copied ? 'Copied!' : 'Copy'"
        @click="_copyCode"
      >
        <!-- Inline SVG so we don't pull the lucide-vue-next bundle
             just for two 16×16 icons. Stroke = currentColor so the
             existing .code-btn color CSS keeps applying. -->
        <svg
          v-if="!copied"
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
          aria-hidden="true"
        >
          <rect x="9" y="9" width="13" height="13" rx="2" />
          <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
        </svg>
        <svg
          v-else
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
          aria-hidden="true"
        >
          <polyline points="20 6 9 17 4 12" />
        </svg>
      </button>
    </div>
    <div class="code-content">
      <div class="shiki-wrapper" v-html="html"></div>
    </div>
  </div>
</template>