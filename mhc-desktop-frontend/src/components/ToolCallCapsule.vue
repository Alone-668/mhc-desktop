<script setup lang="ts">
// Tool call capsule — the goal's "横排积累" pills.
//
// Each MCP / Tool call gets its own pill, laid out left-to-right. The
// pill flips colour based on the call's lifecycle:
//
//   pending   → gray, faint border       (args accumulating)
//   executing → tinted border + loader   (tool running)
//   success   → green tick                (result returned)
//   error     → red X                     (tool threw or ok=false)
//
// Clicking the pill toggles a popover (not in the timeline flow)
// showing the full args + result + a copy-args / copy-result /
// retry row at the top. Custom UIs registered via ``toolUiRegistry``
// replace the popover body for that specific tool; the header (name,
// status, elapsed, copy) is always the registry-rendered default.
//
// A "startedAt" prop lets us show an elapsed-time counter while the
// call is executing. The parent (ChatView) stamps it on tool_start
// and clears it on tool_end.

import { computed, onBeforeUnmount, ref } from "vue"
import Icon from "./Icon.vue"
import { toolUiRegistry } from "../lib/toolUiRegistry"

const props = defineProps<{
  name: string
  /** "mcp" for MCP-namespaced calls, "tool" for plain Tool calls.
   *  Drives the icon + colour: MCP is plug + green, Tool is hammer +
   *  purple. */
  kind: "mcp" | "tool"
  status: "pending" | "executing" | "success" | "error"
  args: Record<string, unknown>
  result?: string
  error?: string
  slug: string
  shortName: string
  /** Epoch ms of the tool_start event. Drives the live elapsed-time
   *  counter shown next to the tool name while executing. */
  startedAt?: number
  /** Final duration in ms for completed calls. Lets us show
   *  "ran in 3.2s" after success / error so the user knows how long
   *  the call took. */
  durationMs?: number
}>()

const open = ref(false)
const popover = ref<HTMLElement | null>(null)
const pillEl = ref<HTMLElement | null>(null)

const CustomUI = computed(() => toolUiRegistry.get(props.name))
const callKind = computed<"mcp" | "tool">(() => props.kind)
const isFlashing = computed(
  () => props.status === "pending" || props.status === "executing",
)
// Show elapsed time live while executing (ticks every 250ms), or
// the final duration after the call completes.
const now = ref(Date.now())
let tickHandle: number | null = null
function startTick() {
  if (tickHandle != null) return
  tickHandle = window.setInterval(() => { now.value = Date.now() }, 250)
}
function stopTick() {
  if (tickHandle != null) {
    window.clearInterval(tickHandle)
    tickHandle = null
  }
}
if (props.status === "executing" || props.status === "pending") {
  startTick()
}
onBeforeUnmount(stopTick)

const elapsedMs = computed<number | null>(() => {
  if (props.durationMs != null) return props.durationMs
  if (props.status === "executing" || props.status === "pending") {
    if (!props.startedAt) return null
    return Math.max(0, now.value - props.startedAt)
  }
  return null
})
const elapsedText = computed(() => {
  const ms = elapsedMs.value
  if (ms == null) return ""
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
})

// Popover positioning. We position the popover BELOW the pill by
// default, but flip above if it would overflow the viewport bottom.
const popoverStyle = ref<Record<string, string>>({})
function positionPopover() {
  const p = pillEl.value
  const d = popover.value
  if (!p || !d) return
  const pr = p.getBoundingClientRect()
  const dr = d.getBoundingClientRect()
  const vw = window.innerWidth
  const vh = window.innerHeight
  // Default: below the pill, left-aligned with pill left edge,
  // but shift left if it would overflow the right of viewport.
  let top = pr.bottom + 6
  let left = pr.left
  if (top + dr.height > vh - 8) {
    top = Math.max(8, pr.top - dr.height - 6)
  }
  if (left + dr.width > vw - 8) {
    left = Math.max(8, vw - dr.width - 8)
  }
  popoverStyle.value = {
    position: "fixed",
    top: `${top}px`,
    left: `${left}px`,
  }
}

async function toggle() {
  open.value = !open.value
  if (open.value) {
    await Promise.resolve()
    positionPopover()
  }
}

// Close on outside click.
function onDocClick(e: MouseEvent) {
  if (!open.value) return
  const target = e.target as Node
  if (popover.value?.contains(target)) return
  if (pillEl.value?.contains(target)) return
  open.value = false
}
if (typeof window !== "undefined") {
  window.addEventListener("mousedown", onDocClick)
}
onBeforeUnmount(() => {
  if (typeof window !== "undefined") {
    window.removeEventListener("mousedown", onDocClick)
  }
})

const argsPreview = computed(() => {
  const keys = Object.keys(props.args)
  if (keys.length === 0) return ""
  return keys
    .slice(0, 3)
    .map((k) => `${k}=${JSON.stringify(props.args[k])}`)
    .join(", ")
})
const resultText = computed(() => props.result ?? "")
const errorText = computed(() => props.error ?? "")
const formattedArgs = computed(() => {
  try {
    return JSON.stringify(props.args, null, 2)
  } catch {
    return String(props.args)
  }
})

async function copyText(text: string) {
  if (navigator.clipboard?.writeText) {
    try { await navigator.clipboard.writeText(text); return } catch {}
  }
  try {
    const ta = document.createElement("textarea")
    ta.value = text
    ta.style.cssText = "position:fixed;left:-10000px;top:-10000px;opacity:0;"
    document.body.appendChild(ta)
    ta.select()
    document.execCommand("copy")
    document.body.removeChild(ta)
  } catch {}
}

// Status icon shown on the right edge of the pill. SVG glyph for
// each state so colour-blind users get a non-colour cue as well.
const statusIcon = computed(() => {
  switch (props.status) {
    case "pending": return "circle"
    case "executing": return "loader"
    case "success": return "check"
    case "error": return "x"
  }
})
// Kind icon (left edge). Plug for MCP, hammer for Tool.
const kindIcon = computed(() => (callKind.value === "mcp" ? "plug" : "hammer"))
</script>

<template>
  <div
    class="tc"
    :class="['tc-' + status, 'tc-kind-' + callKind, { flashing: isFlashing, open }]"
    role="listitem"
  >
    <button
      ref="pillEl"
      class="tc-pill"
      :title="`${slug}::${shortName}`"
      @click="toggle"
    >
      <span class="tc-icon" aria-hidden="true">
        <Icon :name="kindIcon" :width="13" :height="13" />
      </span>
      <span class="tc-kind" :class="'tc-kind-' + callKind">{{
        callKind === "tool" ? "Tool" : "MCP"
      }}</span>
      <span class="tc-name">{{ shortName }}</span>
      <span v-if="elapsedText" class="tc-elapsed">{{ elapsedText }}</span>
      <span class="tc-status" :class="'tc-status-' + status" aria-hidden="true">
        <Icon :name="statusIcon" :width="11" :height="11" />
      </span>
    </button>

    <Teleport to="body">
      <div
        v-if="open"
        ref="popover"
        class="tc-popover"
        :style="popoverStyle"
      >
        <div class="tc-head">
          <div class="tc-head-title">
            <Icon :name="kindIcon" :width="13" :height="13" />
            <span class="tc-head-slug">{{ slug }}</span>
            <span class="tc-head-sep">::</span>
            <span class="tc-head-name">{{ shortName }}</span>
          </div>
          <button class="tc-x" :title="'Close'" @click="open = false">
            <Icon name="x" :width="12" :height="12" />
          </button>
        </div>
        <div class="tc-head-meta">
          <span class="tc-status-pill" :class="'tc-status-pill-' + status">
            <Icon :name="statusIcon" :width="10" :height="10" />
            <span>{{ status }}</span>
          </span>
          <span v-if="elapsedText" class="tc-head-time">{{ elapsedText }}</span>
        </div>

        <CustomUI
          v-if="CustomUI"
          :name="name"
          :status="status"
          :args="args"
          :result="result"
          :error="error"
          :slug="slug"
          :short-name="shortName"
        />
        <div v-else class="tc-fallback">
          <div class="tc-section">
            <div class="tc-section-row">
              <span class="tc-section-label">args</span>
              <button class="tc-mini" @click="copyText(formattedArgs)">
                <Icon name="copy" :width="11" :height="11" />
                <span>Copy</span>
              </button>
            </div>
            <pre class="tc-code">{{ formattedArgs }}</pre>
          </div>
          <div v-if="resultText || status === 'success'" class="tc-section">
            <div class="tc-section-row">
              <span class="tc-section-label">result</span>
              <button class="tc-mini" @click="copyText(resultText || '')">
                <Icon name="copy" :width="11" :height="11" />
                <span>Copy</span>
              </button>
            </div>
            <pre class="tc-code">{{ resultText || "(empty)" }}</pre>
          </div>
          <div v-if="errorText" class="tc-section tc-section-error">
            <div class="tc-section-label">error</div>
            <pre class="tc-code">{{ errorText }}</pre>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.tc {
  display: inline-flex;
  flex-direction: column;
  position: relative;
}
.tc-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 24px;
  padding: 0 10px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--bg);
  font-size: 11.5px;
  color: var(--text);
  cursor: pointer;
  transition: border-color 120ms ease, color 120ms ease, background 120ms ease;
}
.tc-pill:hover {
  border-color: var(--border-mid);
  background: var(--bg-subtle);
}
.tc-icon {
  display: inline-flex;
  align-items: center;
  color: var(--text-mid);
}
.tc-name {
  font-weight: 500;
  font-variant-numeric: tabular-nums;
}
.tc-elapsed {
  font-size: 10px;
  color: var(--text-faint);
  font-variant-numeric: tabular-nums;
  margin-left: 2px;
}
.tc-status {
  display: inline-flex;
  align-items: center;
  color: var(--text-faint);
}
.tc-status.tc-status-executing {
  color: var(--accent);
}
.tc-status.tc-status-success {
  color: #16a34a;
}
.tc-status.tc-status-error {
  color: #dc2626;
}
.tc-status.tc-status-pending {
  color: var(--text-faint);
}

/* Spinner for executing state. We rotate the loader SVG. */
.tc-status.tc-status-executing :deep(svg) {
  animation: tc-spin 0.9s linear infinite;
}
@keyframes tc-spin {
  to { transform: rotate(360deg); }
}

/* Kind badge — small coloured chip for MCP / Tool. */
.tc-kind {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  padding: 1px 5px;
  border-radius: 3px;
  background: var(--bg-subtle);
  border: 1px solid var(--border);
  line-height: 1.4;
}
.tc-kind.tc-kind-mcp {
  background: rgba(22, 163, 74, 0.10);
  color: #16a34a;
  border-color: rgba(22, 163, 74, 0.30);
}
.tc-kind.tc-kind-tool {
  background: rgba(124, 58, 237, 0.10);
  color: #7c3aed;
  border-color: rgba(124, 58, 237, 0.30);
}

/* State-driven border tint. While pending/executing the border
   shifts slightly; on success/error it locks into the outcome
   colour. MCP stays in its green family, Tool stays purple —
   the user can still tell at a glance which subsystem handled
   the call. */
.tc.tc-pending .tc-pill {
  border-color: var(--border-mid);
}
.tc.tc-executing .tc-pill {
  border-color: var(--accent);
}
.tc.tc-kind-mcp.tc-success .tc-pill {
  border-color: rgba(22, 163, 74, 0.55);
}
.tc.tc-kind-mcp.tc-error .tc-pill {
  border-color: rgba(220, 38, 38, 0.55);
}
.tc.tc-kind-tool.tc-success .tc-pill {
  border-color: rgba(124, 58, 237, 0.55);
}
.tc.tc-kind-tool.tc-error .tc-pill {
  border-color: rgba(220, 38, 38, 0.55);
}
/* Tool-kind overrides the executing tint to purple so MCP and Tool
   don't share the same accent. */
.tc.tc-kind-tool.tc-executing .tc-pill {
  border-color: #7c3aed;
}

/* Subtle flash while pending/executing: only the LEFT edge pulses,
   not the full border. Less noisy when many capsules are flashing
   in parallel. */
.tc.flashing .tc-pill {
  animation: tc-pulse-edge 1.4s ease-in-out infinite;
  animation-delay: calc(var(--tc-index, 0) * 80ms);
}
@keyframes tc-pulse-edge {
  0%, 100% { box-shadow: inset 2px 0 0 transparent; }
  50%      { box-shadow: inset 2px 0 0 var(--tc-flash, var(--accent)); }
}
.tc.tc-pending.flashing { --tc-flash: var(--text-faint); }
.tc.tc-kind-mcp.tc-executing.flashing { --tc-flash: var(--accent); }
.tc.tc-kind-tool.tc-executing.flashing { --tc-flash: #7c3aed; }

/* Popover. Teleported to body so it doesn't get clipped by the
   conversation column or any ancestor overflow. */
.tc-popover {
  z-index: 1000;
  min-width: 280px;
  max-width: 480px;
  padding: 10px 12px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 10px;
  box-shadow: var(--shadow-strong);
  font-size: 12px;
  color: var(--text);
}
.tc-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.tc-head-title {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text);
  min-width: 0;
}
.tc-head-slug {
  color: var(--text-faint);
}
.tc-head-sep {
  color: var(--text-faint);
  opacity: 0.6;
}
.tc-head-name {
  font-weight: 600;
  color: var(--text);
}
.tc-x {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  color: var(--text-faint);
  cursor: pointer;
  transition: background 120ms ease, color 120ms ease;
}
.tc-x:hover {
  background: var(--bg-subtle);
  color: var(--text);
}
.tc-head-meta {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin-top: 6px;
  margin-bottom: 8px;
  font-size: 11px;
  color: var(--text-faint);
}
.tc-status-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 6px;
  border-radius: 999px;
  background: var(--bg-subtle);
  border: 1px solid var(--border);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  font-weight: 600;
  font-size: 9.5px;
}
.tc-status-pill.tc-status-pill-success {
  background: rgba(22, 163, 74, 0.10);
  color: #16a34a;
  border-color: rgba(22, 163, 74, 0.30);
}
.tc-status-pill.tc-status-pill-error {
  background: rgba(220, 38, 38, 0.10);
  color: #dc2626;
  border-color: rgba(220, 38, 38, 0.30);
}
.tc-status-pill.tc-status-pill-executing {
  background: rgba(59, 130, 246, 0.10);
  color: var(--accent);
  border-color: rgba(59, 130, 246, 0.30);
}
.tc-status-pill.tc-status-pill-pending {
  background: var(--bg-subtle);
  color: var(--text-faint);
}
.tc-head-time {
  font-variant-numeric: tabular-nums;
}

.tc-fallback {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.tc-section {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.tc-section-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.tc-section-label {
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--text-faint);
}
.tc-section-error .tc-section-label {
  color: #dc2626;
}
.tc-mini {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 20px;
  padding: 0 6px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: transparent;
  color: var(--text-faint);
  font-size: 10.5px;
  cursor: pointer;
  transition: color 120ms ease, border-color 120ms ease;
}
.tc-mini:hover {
  color: var(--text);
  border-color: var(--border-mid);
}
.tc-code {
  margin: 0;
  padding: 8px 10px;
  background: var(--bg-subtle);
  border: 1px solid var(--border-faint);
  border-radius: 6px;
  font-family: var(--font-mono);
  font-size: 11.5px;
  line-height: 1.5;
  color: var(--text);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 200px;
  overflow-y: auto;
}
</style>