<script setup lang="ts">
// Skill icon: emoji from SKILL.md frontmatter (``icon: …``) when the
// market meta carries one, otherwise a deterministic letter avatar —
// slug-derived hue so the same skill always renders the same colors.
import { computed } from "vue"

const props = defineProps<{
  icon?: string
  name: string
  size?: number
}>()

const px = computed(() => `${props.size ?? 40}px`)
const emoji = computed(() => {
  const i = (props.icon ?? "").trim()
  // Keep it to a single grapheme-ish chunk; frontmatter may contain
  // long strings if someone abuses the field.
  return i ? Array.from(i)[0] : ""
})
const letter = computed(
  () => (props.name || "?").trim().charAt(0).toUpperCase(),
)
const hue = computed(() => {
  let h = 0
  for (const ch of props.name || "") h = (h * 31 + ch.charCodeAt(0)) % 360
  return h
})
const style = computed(() => {
  if (emoji.value) {
    return { background: "var(--bg-hover)" }
  }
  return {
    background: `linear-gradient(135deg, hsl(${hue.value} 58% 92%), hsl(${(hue.value + 40) % 360} 58% 84%))`,
    color: `hsl(${hue.value} 45% 26%)`,
  }
})
</script>

<template>
  <span
    class="mkt-icon"
    :style="{ '--sz': px, width: px, height: px, ...style }"
  >
    <span v-if="emoji" class="emoji">{{ emoji }}</span>
    <span v-else class="letter">{{ letter }}</span>
  </span>
</template>

<style scoped>
.mkt-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: calc(var(--sz, 40px) * 0.24);
  flex-shrink: 0;
  font-weight: 700;
  user-select: none;
  border: 1px solid var(--border);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.55), 0 1px 2px rgba(16, 19, 26, 0.06);
  overflow: hidden;
}
.emoji {
  font-size: calc(var(--sz, 40px) * 0.5);
  line-height: 1;
}
.letter {
  font-size: calc(var(--sz, 40px) * 0.44);
  line-height: 1;
}
</style>
