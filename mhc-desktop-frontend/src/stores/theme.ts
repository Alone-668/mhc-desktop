import { defineStore } from "pinia"
import { ref } from "vue"

export type Theme = "light" | "dark"
const LS_KEY = "mhc.theme"

export const useThemeStore = defineStore("theme", () => {
  const theme = ref<Theme>("light")

  function apply() {
    document.documentElement.setAttribute("data-theme", theme.value)
  }

  function init() {
    let saved: Theme | null = null
    try {
      const v = localStorage.getItem(LS_KEY)
      if (v === "light" || v === "dark") saved = v
    } catch {
      /* ignore */
    }
    if (saved) theme.value = saved
    apply()
  }

  function toggle() {
    theme.value = theme.value === "light" ? "dark" : "light"
    apply()
    try {
      localStorage.setItem(LS_KEY, theme.value)
    } catch {
      /* ignore */
    }
  }

  return { theme, init, toggle }
})
