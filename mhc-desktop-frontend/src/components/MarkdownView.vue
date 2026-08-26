<script setup lang="ts">
// Markdown rendering for assistant messages, using @incremark/vue.
//
// Why Incremark: it parses markdown incrementally as chunks arrive so
// streaming text doesn't trigger a full re-parse on every chunk.
// Each block transitions from "pending" → "completed" as the model
// finishes it, so partial responses don't show broken markdown.
//
// While ``streaming`` is true, we feed new content via ``append`` and
// don't call ``finalize`` so the last block keeps its pending state.
// On ``done``/``error``/``cancelled`` we call ``finalize`` so the
// last block locks in.
//
// Syntax highlighting is provided by Shiki, loaded asynchronously
// by Incremark's default ``IncremarkCodeDefault`` component. We don't
// need to configure anything — the package's @incremark/theme
// handles language registration lazily. The rendered code blocks come
// back as ``<div class="incremark-code">`` with a header that shows
// the language and a built-in copy button; we restyle those in the
// CSS below so they match the rest of the app rather than the
// theme's defaults.

import { ref, watch } from "vue"
import { useIncremark, Incremark } from "@incremark/vue"
import "@incremark/theme/styles.css"
import CodeBlock from "./CodeBlock.vue"

const props = defineProps<{
  source: string
  streaming: boolean
}>()

const { blocks, append, finalize, reset } = useIncremark()
const lastSource = ref("")

// Override Incremark's default code renderer. Incremark ships with
// ``IncremarkCodeDefault`` which hardcodes the Shiki theme to
// ``github-dark`` and offers no prop to switch — that theme emits
// light-pastel token colors designed for a dark surface, so on the
// app's light page the code is unreadable. ``CodeBlock`` swaps the
// theme based on the current app theme (see ``CodeBlock.vue`` for
// the full rationale).
const codeComponents = { code: CodeBlock }

function _resync() {
  // Source text changed externally (e.g. session switch brought in a
  // different assistant message). Replace the in-progress parse.
  reset()
  if (props.source) {
    append(props.source)
    if (!props.streaming) finalize()
  }
  lastSource.value = props.source
}

watch(
  () => `${props.source}::${props.streaming ? "1" : "0"}`,
  (key) => {
    const src = key.split("::")[0]
    const stream = key.endsWith("::1")
    if (src !== lastSource.value) {
      _resync()
      return
    }
    // Source unchanged but streaming flag flipped (e.g. done event
    // landed) — finalize so the last block renders as completed.
    if (!stream) finalize()
  },
  { immediate: true },
)
</script>

<template>
  <div class="md">
    <Incremark :blocks="blocks" :components="codeComponents" />
  </div>
</template>

<style>
/* Styles for the rendered markdown itself. NOT scoped — the inner
   Incremark component renders global HTML (h1, p, code, etc.) so a
   scoped selector wouldn't reach them. The .md wrapper on the
   outer <div> keeps these rules contained.

   Token palette mirrors the rest of the app's --text-* / --accent-*
   variables so light + dark themes both look right. */
.md p {
  margin: 0 0 12px;
  color: var(--text);
}
.md p:last-child {
  margin-bottom: 0;
}
.md h1,
.md h2,
.md h3,
.md h4 {
  color: var(--text);
  margin: 16px 0 8px;
  font-weight: 600;
  letter-spacing: -0.01em;
}
.md h1 { font-size: 20px; }
.md h2 { font-size: 17px; }
.md h3 { font-size: 15px; }
.md h4 { font-size: 14px; }
.md ul,
.md ol {
  margin: 0 0 12px;
  padding-left: 22px;
  color: var(--text);
}
.md li {
  margin: 4px 0;
}

/* Inline code: no border (would clash with prose rhythm), just a
   faint tinted pill that reads as "code without being a button". */
.md code {
  font-family: var(--font-mono);
  font-size: 0.88em;
  padding: 1px 6px;
  border-radius: 4px;
  background: color-mix(in srgb, var(--bg) 88%, var(--text));
  border: 0;
  color: var(--text);
  line-height: 1.5;
}
/* Markdown fallback for code blocks (e.g. plain text mode without a
   language header). Our custom ``CodeBlock`` component (which
   replaces Incremark's default) renders into the same wrapper
   classes — ``.incremark-code`` / ``.code-header`` /
   ``.shiki-wrapper`` — so the rules below keep applying unchanged. */
.md pre {
  margin: 0 0 12px;
  padding: 12px 14px;
  border-radius: 10px;
  background: transparent;
  border: 1px solid var(--border-mid);
  overflow-x: auto;
  font-size: 13px;
  line-height: 1.55;
}
.md pre code {
  border: 0;
  background: transparent;
  padding: 0;
  font-size: inherit;
  color: inherit;
}

/* Incremark code block wrapper. The bg follows ``--code-block-bg``
   so the surface stays light in light mode and dark in dark mode —
   the Shiki theme picked by ``CodeBlock`` is designed for whichever
   surface is active. */
.md .incremark-code {
  margin: 0 0 12px;
  border: 1px solid var(--code-block-border);
  border-radius: 10px;
  overflow: hidden;
  background: var(--code-block-bg);
}
.md .incremark-code .code-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 12px;
  background: var(--bg-subtle);
  border-bottom: 1px solid var(--border);
  font-size: 11px;
  min-height: 32px;
  color: var(--text-faint);
}
.md .incremark-code .code-header .language {
  font-family: var(--font-mono);
  font-size: 10.5px;
  font-weight: 600;
  text-transform: lowercase;
  letter-spacing: 0.04em;
  color: var(--text-mid);
}
.md .incremark-code .code-btn {
  width: 22px;
  height: 22px;
  border-radius: 5px;
  color: var(--text-faint);
  opacity: 1;
}
.md .incremark-code .code-btn:hover {
  background: var(--bg-hover);
  color: var(--text);
}
.md .incremark-code .code-content {
  padding: 0;
  background: var(--code-block-bg);
}
/* Shiki sets inline ``background-color`` on its own ``<pre>`` to
   the theme's surface color (white for github-light, dark for
   github-dark). Our theme token matches that surface, so the
   inline color agrees with the wrapper. We still force the
   wrapper color via ``!important`` so the box stays consistent
   even if Shiki's inline color is wrong for a future theme. */
.md .incremark-code .shiki-wrapper pre,
.md .incremark-code .shiki-wrapper .shiki {
  margin: 0;
  padding: 12px 14px;
  background-color: var(--code-block-bg) !important;
  color: var(--code-block-fg);
  font-size: 13px;
  line-height: 1.55;
}
/* Plain-text fallback (no language) and Shiki's brief loading
 * skeleton both render as ``<pre><code>`` inside the wrapper.
 * Force the wrapper bg/fg so they read in either app theme. */
.md .incremark-code .code-fallback pre,
.md .incremark-code .code-loading pre {
  margin: 0;
  padding: 12px 14px;
  background: var(--code-block-bg);
  color: var(--code-block-fg);
  font-size: 13px;
  line-height: 1.55;
}
.md .incremark-code .code-fallback code,
.md .incremark-code .code-loading code {
  color: var(--code-block-fg);
  font-family: var(--font-mono);
}

.md blockquote {
  margin: 0 0 12px;
  padding: 6px 14px;
  border-left: 3px solid var(--accent);
  background: transparent;
  border-radius: 0 8px 8px 0;
  color: var(--text);
}
.md table {
  border-collapse: collapse;
  margin: 0 0 12px;
  width: auto;
  font-size: 13px;
}
.md th,
.md td {
  border: 1px solid var(--border);
  padding: 6px 10px;
  text-align: left;
}
.md th {
  background: transparent;
  font-weight: 600;
  border-bottom: 2px solid var(--border-mid);
}
.md a {
  color: var(--accent);
  text-decoration: underline;
  text-decoration-thickness: 1px;
  text-underline-offset: 3px;
}
.md hr {
  border: 0;
  border-top: 1px solid var(--border);
  margin: 16px 0;
}
.md strong {
  font-weight: 600;
  color: var(--text);
}

/* While a block is still pending (the model is mid-streaming it),
   draw a thin underline that slides left-to-right to mark which
   line is currently growing. */
.md [data-incremark-pending] {
  background-image: linear-gradient(
    90deg,
    var(--text-faint) 0%,
    transparent 100%
  );
  background-repeat: no-repeat;
  background-position: 0 100%;
  background-size: 0% 1px;
  animation: md-shimmer 1.4s ease-in-out infinite;
}
@keyframes md-shimmer {
  0% { background-size: 0% 1px; background-position: 0 100%; }
  50% { background-size: 100% 1px; background-position: 0 100%; }
  100% { background-size: 100% 1px; background-position: 100% 100%; }
}
</style>