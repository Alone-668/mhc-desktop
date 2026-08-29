<script setup lang="ts">
import { computed, ref } from "vue"

const props = defineProps<{
  icon?: string
  name: string
  size?: number
}>()

const px = computed(() => `${props.size ?? 40}px`)
const emoji = computed(() => {
  const i = (props.icon ?? "").trim()
  return i ? Array.from(i)[0] : ""
})
const letter = computed(() => (props.name || "?").trim().charAt(0).toUpperCase())
const hue = computed(() => {
  let h = 0
  for (const ch of props.name || "") h = (h * 31 + ch.charCodeAt(0)) % 360
  return h
})
const style = computed(() =>
  emoji.value
    ? {}
    : {
        background: `linear-gradient(135deg, hsl(${hue.value} 65% 55%), hsl(${(hue.value + 40) % 360} 65% 45%))`,
      },
)
</script>

<template>
  <span class="mkt-icon" :style="{ '--sz': px, width: px, height: px, ...style }">
    <span v-if="emoji" style="font-size: calc(var(--sz) * 0.55)">{{ emoji }}</span>
    <span v-else style="font-size: calc(var(--sz) * 0.45)">{{ letter }}</span>
  </span>
</template>
