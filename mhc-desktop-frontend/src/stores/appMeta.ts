import { defineStore } from "pinia"
import { ref, watchEffect } from "vue"

// User-customisable app title. Drives the title bar (rendered uppercase
// via CSS text-transform, which is a no-op for CJK so Chinese titles
// display as-is) and the left-nav brand label (rendered verbatim).
// Persisted in localStorage so the user's choice survives reload.
const LS_KEY = "mhc.appTitle"
const DEFAULT_TITLE = "mhc-desktop"

// Read the saved title at module init time. We can't do this inside
// the store factory — ``watchEffect``'s first synchronous tick would
// fire with the default value and overwrite the saved one before
// the factory had a chance to call ``init()`` and pull it back.
function _readSaved(): string {
  try {
    const v = localStorage.getItem(LS_KEY)
    if (typeof v === "string" && v.trim()) return v.trim()
  } catch {
    /* ignore */
  }
  return DEFAULT_TITLE
}

export const useAppMetaStore = defineStore("appMeta", () => {
  const title = ref(_readSaved())

  // ``init`` is kept for symmetry with the theme store but is now a
  // no-op: the value is already loaded from localStorage by the
  // factory above.
  function init() {
    /* no-op — see _readSaved */
  }

  function setTitle(next: string) {
    const v = (next || "").trim().slice(0, 64)
    title.value = v || DEFAULT_TITLE
  }

  function reset() {
    title.value = DEFAULT_TITLE
  }

  // Auto-persist on change; no debounce needed for a one-line key.
  watchEffect(() => {
    try {
      localStorage.setItem(LS_KEY, title.value)
    } catch {
      /* ignore */
    }
  })

  return { title, init, setTitle, reset }
})