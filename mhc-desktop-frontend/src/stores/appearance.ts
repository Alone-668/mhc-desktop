import { defineStore } from "pinia"
import { ref } from "vue"

// Slider range is intentionally narrow (12-20): the chat text baseline
// is 14px; 20px is large but still readable. Going bigger makes
// bubbles overflow the chat width on small windows.
const MIN = 12
const MAX = 20
const DEFAULT = 14
const LS_KEY = "mhc.fontSize"

function clamp(n: number): number {
  if (!Number.isFinite(n)) return DEFAULT
  return Math.min(MAX, Math.max(MIN, Math.round(n)))
}

export const useAppearanceStore = defineStore("appearance", () => {
  const fontSize = ref<number>(DEFAULT)

  function apply() {
    // :root is <html>; inline style beats tokens.css so this is the
    // single source of truth while the app runs.
    document.documentElement.style.setProperty(
      "--app-font-size",
      `${fontSize.value}px`,
    )
  }

  function init() {
    let saved: number | null = null
    try {
      const v = localStorage.getItem(LS_KEY)
      if (v !== null) saved = clamp(Number(v))
    } catch {
      /* ignore */
    }
    fontSize.value = saved ?? DEFAULT
    apply()
  }

  function setFontSize(px: number) {
    fontSize.value = clamp(px)
    apply()
    try {
      localStorage.setItem(LS_KEY, String(fontSize.value))
    } catch {
      /* ignore */
    }
  }

  return { fontSize, min: MIN, max: MAX, init, setFontSize }
})
