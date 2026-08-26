<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue"
import { useConfirm, type ConfirmTone } from "../lib/confirm"
import Icon, { type IconName } from "./Icon.vue"
import { t } from "../i18n"

const store = useConfirm()
const cardRef = ref<HTMLDivElement | null>(null)

// Tone-driven defaults so call sites can stay terse. Each preset
// points at an i18n key (resolved through t() below), not at a
// raw string — otherwise the buttons would render the literal key.
const TONE_PRESETS: Record<
  ConfirmTone,
  { confirmKey: string; cancelKey: string; iconName: IconName; iconColor: string }
> = {
  default: {
    confirmKey: "common.confirm",
    cancelKey: "common.cancel",
    iconName: "help",
    iconColor: "var(--accent)",
  },
  danger: {
    confirmKey: "common.delete",
    cancelKey: "common.cancel",
    iconName: "trash",
    iconColor: "var(--danger)",
  },
}

const preset = computed(() => TONE_PRESETS[store.tone ?? "default"])

// Fallback chain: caller-supplied label wins; otherwise the tone's
// default key, resolved through the current locale.
function confirmText(): string {
  if (store.confirmLabel) return store.confirmLabel
  return t(preset.value.confirmKey)
}
function cancelText(): string {
  if (store.cancelLabel) return store.cancelLabel
  return t(preset.value.cancelKey)
}

// Focus the cancel button on open so Enter doesn't immediately confirm
// destructive actions; the confirm button is still keyboard-reachable
// via Tab.
async function focusCard() {
  await nextTick()
  const target =
    cardRef.value?.querySelector<HTMLButtonElement>(".confirm-cancel") ??
    cardRef.value
  target?.focus()
}

watch(
  () => store.open,
  (v) => {
    if (v) focusCard()
  },
)

function onKeydown(e: KeyboardEvent) {
  if (!store.open) return
  if (e.key === "Escape") {
    e.preventDefault()
    store.cancel()
  } else if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault()
    store.confirm()
  }
}

if (typeof window !== "undefined") {
  window.addEventListener("keydown", onKeydown)
  onBeforeUnmount(() => window.removeEventListener("keydown", onKeydown))
}
</script>

<template>
  <Teleport to="body">
    <Transition name="confirm">
      <div
        v-if="store.open"
        class="confirm-backdrop"
        @mousedown.self="store.cancel()"
        role="presentation"
      >
        <div
          ref="cardRef"
          class="confirm-card"
          role="alertdialog"
          aria-modal="true"
          :aria-labelledby="store.title ? 'confirm-title' : undefined"
          :aria-describedby="store.message ? 'confirm-message' : undefined"
        >
          <div class="confirm-head">
            <span class="confirm-icon" :style="{ color: preset.iconColor }">
              <Icon :name="preset.iconName" />
            </span>
            <h3 v-if="store.title" id="confirm-title" class="confirm-title">
              {{ store.title }}
            </h3>
            <p v-if="store.message" id="confirm-message" class="confirm-message">
              {{ store.message }}
            </p>
          </div>
          <div class="confirm-actions">
            <button
              type="button"
              class="confirm-cancel"
              @click="store.cancel()"
            >
              {{ cancelText() }}
            </button>
            <button
              type="button"
              :class="['confirm-ok', store.tone === 'danger' ? 'danger' : 'primary']"
              @click="store.confirm()"
            >
              {{ confirmText() }}
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style>
.confirm-backdrop {
  position: fixed;
  inset: 0;
  /* Tinted dark, not pure black — keeps the page's hue visible
   * through the overlay so the modal feels like a layer over the
   * app, not a black hole. */
  background: rgba(15, 23, 42, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 10000;
  padding: 24px;
}
.confirm-card {
  width: min(440px, 92vw);
  background: var(--bg-panel, var(--bg));
  color: var(--text);
  border: 1px solid var(--border);
  /* Shape consistency: cards and buttons both use 6px so the
   * dialog reads as part of the same surface family. */
  border-radius: 6px;
  box-shadow:
    0 1px 0 rgba(15, 23, 42, 0.04),
    0 12px 32px rgba(15, 23, 42, 0.18);
  padding: 22px 22px 18px;
  outline: none;
}
.confirm-head {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 10px;
}
.confirm-icon {
  display: inline-flex;
  width: 32px;
  height: 32px;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  background: var(--bg-subtle, var(--bg));
  border: 1px solid var(--border);
}
.confirm-title {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  letter-spacing: -0.005em;
  color: var(--text);
}
.confirm-message {
  margin: 0;
  font-size: 13px;
  line-height: 1.55;
  color: var(--text-mid);
}
.confirm-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 20px;
}
.confirm-cancel,
.confirm-ok {
  font: inherit;
  font-size: 13px;
  font-weight: 500;
  padding: 7px 16px;
  border-radius: 6px;
  border: 1px solid var(--border);
  background: var(--bg);
  color: var(--text);
  cursor: pointer;
  transition: background 120ms ease, border-color 120ms ease, color 120ms ease;
}
.confirm-cancel:hover {
  background: var(--bg-hover);
}
/* Primary action uses accent for fill and a fixed off-white text
 * color. Fixed (not var(--bg)) so the contrast survives theme
 * swaps where --bg might be light. */
.confirm-ok.primary {
  background: var(--accent);
  border-color: var(--accent);
  color: #ffffff;
}
.confirm-ok.primary:hover {
  filter: brightness(1.08);
}
.confirm-ok.danger {
  /* No --danger token in the design system yet; use the same rose
   * hue as the close-button hover so the danger affordance
   * matches what's already familiar in the title bar. */
  background: #e85a6a;
  border-color: #e85a6a;
  color: #ffffff;
}
.confirm-ok.danger:hover {
  background: #d04a59;
  border-color: #d04a59;
}
.confirm-cancel:focus-visible,
.confirm-ok:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}

.confirm-enter-active,
.confirm-leave-active {
  transition: opacity 140ms ease;
}
.confirm-enter-from,
.confirm-leave-to {
  opacity: 0;
}
</style>