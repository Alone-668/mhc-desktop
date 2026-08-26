// Onboarding overlay state.
//
// The store is tiny on purpose: it owns three booleans
// (visible / done / loading), the card list, and a couple of
// imperative helpers (open / next / prev / dismiss). The localStorage
// flag is the source of truth for "has the user seen this?": we read
// it once at construction and write it back on dismiss, so a refresh
// after dismissal re-opens the app straight into the chat surface.

import { computed, ref } from "vue"
import { defineStore } from "pinia"
import { api, type OnboardingCard } from "../api/client"

const LS_DONE = "mhc.onboarding.done"
const LS_INDEX = "mhc.onboarding.index"

function safeRead(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

function safeWrite(key: string, value: string) {
  try {
    localStorage.setItem(key, value)
  } catch {
    // localStorage may be disabled (privacy mode); the overlay
    // still works for the current page lifetime, it just won't
    // remember dismissal. Better than crashing the boot path.
  }
}

function readDone(): boolean {
  return safeRead(LS_DONE) === "1"
}

function readIndex(): number {
  const raw = safeRead(LS_INDEX)
  if (!raw) return 0
  const n = Number.parseInt(raw, 10)
  return Number.isFinite(n) && n >= 0 ? n : 0
}

export const useOnboardingStore = defineStore("onboarding", () => {
  // `visible` is independent of `done`: the store keeps the card
  // list loaded even after dismissal so SettingsView (or a future
  // "show tour again" button) can re-open the overlay without a
  // re-fetch. `done` is the persistence flag; `visible` is the
  // rendering flag.
  const done = ref<boolean>(readDone())
  const visible = ref<boolean>(false)
  const loading = ref<boolean>(false)
  const error = ref<string | null>(null)
  const cards = ref<OnboardingCard[]>([])
  const index = ref<number>(readIndex())

  const current = computed<OnboardingCard | null>(
    () => cards.value[index.value] ?? null,
  )
  const isLast = computed(() => index.value >= cards.value.length - 1)
  const total = computed(() => cards.value.length)

  async function load() {
    if (cards.value.length > 0 || loading.value) return
    loading.value = true
    error.value = null
    try {
      cards.value = await api.listOnboarding()
      // Clamp index in case the card list shrank between sessions.
      if (index.value >= cards.value.length) {
        index.value = Math.max(0, cards.value.length - 1)
        safeWrite(LS_INDEX, String(index.value))
      }
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
      cards.value = []
    } finally {
      loading.value = false
    }
  }

  /** Background re-fetch — used when the locale flips in Settings so
   *  the backend's resolved ``title`` / ``body`` strings match the
   *  new Accept-Language on the next render. We keep the existing
   *  card list mounted while the fetch is in flight so the overlay
   *  doesn't flicker (the component reads the i18n dicts
   *  reactively, so the user sees the new language immediately
   *  anyway). */
  async function reload() {
    loading.value = true
    try {
      const fresh = await api.listOnboarding()
      // Only swap if we still have a card list of the same length
      // — guards against a backend that shipped a different layout
      // mid-tour and would otherwise bump the user to a different
      // card.
      if (fresh.length === cards.value.length) {
        cards.value = fresh
      }
    } catch {
      // Reload is best-effort; the i18n dicts are already in
      // memory and the overlay keeps rendering.
    } finally {
      loading.value = false
    }
  }

  // Called on first mount by App.vue. Loads the cards if we have
  // not yet shown the overlay to the user, then opens it.
  async function bootstrap() {
    if (done.value) return
    await load()
    if (cards.value.length > 0) visible.value = true
  }

  function open() {
    if (cards.value.length === 0) {
      // Caller forgot to await load() — fire and forget; the
      // overlay will appear once the fetch resolves.
      void load().then(() => {
        if (cards.value.length > 0) visible.value = true
      })
      return
    }
    visible.value = true
  }

  function next() {
    if (index.value < cards.value.length - 1) {
      index.value += 1
      safeWrite(LS_INDEX, String(index.value))
    }
  }

  function prev() {
    if (index.value > 0) {
      index.value -= 1
      safeWrite(LS_INDEX, String(index.value))
    }
  }

  function goTo(i: number) {
    if (i >= 0 && i < cards.value.length) {
      index.value = i
      safeWrite(LS_INDEX, String(i))
    }
  }

  function dismiss() {
    // "知道了" — close the overlay and remember that the user has
    // seen it. We don't clear `cards` so SettingsView (or a future
    // "play again" entry point) can re-open the tour cheaply.
    visible.value = false
    done.value = true
    safeWrite(LS_DONE, "1")
  }

  function reset() {
    // Escape hatch for tests and SettingsView. Clears the flag so
    // the next bootstrap() shows the overlay again from card 0.
    done.value = false
    index.value = 0
    safeWrite(LS_DONE, "0")
    safeWrite(LS_INDEX, "0")
  }

  return {
    done,
    visible,
    loading,
    error,
    cards,
    index,
    current,
    isLast,
    total,
    load,
    reload,
    bootstrap,
    open,
    next,
    prev,
    goTo,
    dismiss,
    reset,
  }
})