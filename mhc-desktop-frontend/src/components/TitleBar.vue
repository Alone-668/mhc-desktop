<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue"
import Icon from "./Icon.vue"
import { t } from "../i18n"
import { useAppMetaStore } from "../stores/appMeta"

const appMeta = useAppMetaStore()

// CSS `text-transform: uppercase` is applied to `.title` below; it
// uppercases ASCII letters and is a no-op on CJK glyphs, so Chinese
// titles render as-is while English titles display in caps.
const titleText = computed(() => appMeta.title)

const isMac = computed(() => window.mhc?.platform === "darwin")
const isMax = ref(false)

let unsubscribe: (() => void) | null = null

onMounted(async () => {
  const w = window.mhc?.window
  if (!w) return
  isMax.value = await w.isMaximized()
  unsubscribe = w.onMaximizeChange((max) => {
    isMax.value = max
  })
})

onBeforeUnmount(() => {
  unsubscribe?.()
})

async function minimize() {
  await window.mhc?.window.minimize()
}
async function toggleMaximize() {
  await window.mhc?.window.toggleMaximize()
}
async function close() {
  await window.mhc?.window.close()
}
</script>

<template>
  <header :class="['titlebar', { 'mac-traffic-lights': isMac }]">
    <!-- Product name as a single literal — not localisable. The
         brand has a canonical spelling and we don't want zh to
         show "minimal harness 桌面" (or similar) for a name that
         is the same string everywhere. -->
    <div class="title">{{ titleText }}</div>
    <div class="drag" />
    <div class="controls">
      <button class="ctrl" :title="t('titleBar.minimize')" @click="minimize">
        <Icon name="minus" />
      </button>
      <button
        class="ctrl"
        :title="isMax ? t('titleBar.restore') : t('titleBar.maximize')"
        @click="toggleMaximize"
      >
        <Icon :name="isMax ? 'square-stack' : 'square'" />
      </button>
      <button class="ctrl close" :title="t('titleBar.close')" @click="close">
        <Icon name="x" />
      </button>
    </div>
  </header>
</template>

<style scoped>
.titlebar {
  position: relative;
  flex-shrink: 0;
  height: 28px;
  display: flex;
  align-items: stretch;
  background: var(--bg-panel);
  border-bottom: 1px solid var(--border);
  user-select: none;
}

/* Title block. No logo, just the product name — small, low-emphasis
   text that reads as window chrome rather than as UI. Positioned
   absolutely so it always lands dead-centre of the bar,
   regardless of the widths of the trailing controls or the
   leading macOS traffic lights. ``-webkit-app-region: drag`` so
   clicking the text still drags the window. */
.title {
  position: absolute;
  left: 50%;
  top: 0;
  bottom: 0;
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  padding: 0 14px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.32em;
  text-transform: uppercase;
  color: var(--text-mid);
  -webkit-app-region: drag;
  pointer-events: none; /* let drag events fall through to .drag */
}
.title > * {
  pointer-events: auto; /* but re-enable on the actual text node */
}

/* Spacer — drag handle between title and controls. */
.drag {
  flex: 1;
  -webkit-app-region: drag;
}

.controls {
  display: flex;
  -webkit-app-region: no-drag;
}

/* Modern flat controls — square hit area with a subtle hover
   surface, closer to Arc / Linear / VS Code than to the OS
   default. Hover bg comes in at 8% opacity so the icon stays
   readable against both light and dark themes. */
.ctrl {
  width: 36px;
  height: 100%;
  border: 0;
  background: transparent;
  color: var(--text-mid);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition:
    background 120ms ease,
    color 120ms ease,
    transform 80ms ease;
  padding: 0;
  border-radius: 0;
}
.ctrl:hover {
  background: var(--bg-hover);
  color: var(--text);
}
.ctrl:active {
  transform: scale(0.92);
}

/* Close button gets the conventional accent on hover so it stays
   discoverable, but we drop the saturated red for a more
   restrained rose tone — the icon turns white-on-rose only on
   hover, matching how Arc / Raycast handle the close affordance. */
.ctrl.close:hover {
  background: #e85a6a;
  color: #ffffff;
}
.ctrl.close:active {
  background: #d04a59;
}
</style>
