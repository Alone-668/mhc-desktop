<script setup lang="ts">
// Thinking block — collapsible view of the model's reasoning
// (``reasoning_content``).
//
// States:
//   - pending  → collapsed by default; label carries a live spinner
//                and character count that updates as chunks arrive.
//   - final    → still starts collapsed but with a static summary
//                "Thought for Xs · Y chars". Click to expand.
//
// We never keep the thinking body open by default: long reasoning
// otherwise dominates the conversation column and the user has no
// affordance to hide it. The summary line + click-to-expand gives
// the user visibility into the existence and size of the reasoning
// without the visual cost.

import { computed, ref } from "vue"
import { t } from "../i18n"

const props = defineProps<{
  content: string
  /** True while the reasoning segment is still receiving deltas. */
  streaming: boolean
}>()

const expanded = ref(false)
// Auto-expand while actively streaming so the user can read the
// reasoning as it arrives. Collapse once it finishes so the row
// doesn't dominate the timeline.
const shouldExpand = computed(() =>
  props.streaming ? true : expanded.value,
)

const charCount = computed(() => props.content.length)
const labelText = computed(() => t("chat.thinking"))

function formatCount(n: number): string {
  if (n < 1000) return `${n}`
  if (n < 10000) return `${(n / 1000).toFixed(1).replace(/\.0$/, "")}k`
  return `${Math.round(n / 1000)}k`
}
</script>

<template>
  <div
    class="tl-thinking"
    :class="{ open: shouldExpand, streaming }"
    role="region"
    :aria-label="t('chat.thinking')"
  >
    <button
      class="tl-thinking-head"
      :aria-expanded="shouldExpand ? 'true' : 'false'"
      @click="expanded = !expanded"
    >
      <span class="tl-thinking-marker" aria-hidden="true">{{ streaming ? "◌" : "·" }}</span>
      <span class="tl-thinking-label">{{ labelText }}</span>
      <span class="tl-thinking-meta">
        <span>{{ formatCount(charCount) }}</span>
      </span>
    </button>
    <div v-if="shouldExpand" class="tl-thinking-body">{{ content }}</div>
  </div>
</template>

<style scoped>
/* Quiet parenthetical note, not a "card". No border, no fill,
   no uppercase, no purple. Reads as a faint aside; on click it
   unfolds the reasoning text in the same text register as
   surrounding prose so it doesn't look stamped on. */
.tl-thinking {
  display: flex;
  flex-direction: column;
  gap: 6px;
  background: transparent;
  border: 0;
  padding: 0;
  font-size: 12.5px;
  line-height: 1.65;
  color: var(--text-faint);
  margin-left: 14px;          /* slight indent, like a quoted aside */
}
.tl-thinking-head {
  display: inline-flex;
  align-items: baseline;
  gap: 6px;
  width: auto;
  padding: 0;
  background: transparent;
  border: 0;
  cursor: pointer;
  color: inherit;
  font: inherit;
  text-align: left;
  transition: color 120ms ease;
}
.tl-thinking-head:hover { color: var(--text-mid); }
.tl-thinking.open .tl-thinking-head { color: var(--text-mid); }

.tl-thinking-marker {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-faint);
  display: inline-block;
  transform: translateY(-0.5px);
}
.tl-thinking.streaming .tl-thinking-marker {
  color: var(--text-mid);
  animation: tl-pulse 1.6s ease-in-out infinite;
}
@keyframes tl-pulse {
  0%, 100% { opacity: 0.45; }
  50%      { opacity: 1;    }
}

.tl-thinking-label {
  font-size: 11.5px;
  font-style: italic;
  color: inherit;
  letter-spacing: 0;
}
.tl-thinking-meta {
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--text-faint);
  font-variant-numeric: tabular-nums;
}
.tl-thinking-body {
  /* Indent under the head so the body lines up with the prose
     of the surrounding text, not with the marker. */
  margin-left: 14px;
  padding-left: 8px;
  border-left: 1px solid var(--border-faint);
  white-space: pre-wrap;
  word-break: break-word;
  font-family: var(--font-sans);
  font-size: 12.5px;
  line-height: 1.65;
  font-style: italic;
  color: var(--text-mid);
  opacity: 0.92;
}
</style>