// 主题切换：light / dark。默认跟随系统，可手动切换，持久化。
import { computed, ref } from "vue"

export type Theme = "light" | "dark"
const LS_KEY = "mhc-market.theme"

function detect(): Theme {
  const saved = localStorage.getItem(LS_KEY)
  if (saved === "light" || saved === "dark") return saved
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"
}

export const theme = ref<Theme>(detect())

export const isDark = computed(() => theme.value === "dark")
export const themeLabel = computed(() => (theme.value === "dark" ? "light" : "dark"))

export function toggleTheme() {
  theme.value = theme.value === "dark" ? "light" : "dark"
  applyTheme()
}

export function applyTheme() {
  localStorage.setItem(LS_KEY, theme.value)
  document.documentElement.setAttribute("data-theme", theme.value)
}

// 初始应用 + 跟随系统变化（若用户没手动选过）
applyTheme()
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", (e) => {
  if (!localStorage.getItem(LS_KEY)) {
    theme.value = e.matches ? "dark" : "light"
    applyTheme()
  }
})
