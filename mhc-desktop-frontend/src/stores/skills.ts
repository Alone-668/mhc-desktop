import { computed, ref } from "vue"
import { defineStore } from "pinia"
import { api, type Skill } from "../api/client"

// localStorage key for the *per-session* "include in next message" set.
// Keyed by session id so switching sessions restores the right
// selections; falls back to "_default" before a session exists.
const LS_PREFIX = "mhc.skills.active."

function loadActive(sessionId: string): Set<string> {
  try {
    const raw = localStorage.getItem(LS_PREFIX + sessionId)
    if (!raw) return new Set()
    const arr = JSON.parse(raw)
    return new Set(Array.isArray(arr) ? arr.filter((x) => typeof x === "string") : [])
  } catch {
    return new Set()
  }
}

function saveActive(sessionId: string, set: Set<string>) {
  try {
    localStorage.setItem(LS_PREFIX + sessionId, JSON.stringify([...set]))
  } catch {
    /* ignore */
  }
}

export const useSkillsStore = defineStore("skills", () => {
  const items = ref<Skill[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)
  const currentSessionId = ref<string>("_default")
  const active = ref<Set<string>>(new Set())

  const enabled = computed(() => items.value.filter((s) => s.enabled))

  function setCurrentSession(sid: string | null) {
    currentSessionId.value = sid || "_default"
    active.value = loadActive(currentSessionId.value)
  }

  async function refresh() {
    loading.value = true
    error.value = null
    try {
      items.value = await api.listSkills()
      // Drop active slugs that no longer exist (or were disabled) so we
      // don't keep sending ghosts in chat requests.
      const valid = new Set(
        items.value.filter((s) => s.enabled).map((s) => s.slug),
      )
      const filtered = [...active.value].filter((s) => valid.has(s))
      if (filtered.length !== active.value.size) {
        active.value = new Set(filtered)
        saveActive(currentSessionId.value, active.value)
      }
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
    } finally {
      loading.value = false
    }
  }

  function isActive(slug: string): boolean {
    return active.value.has(slug)
  }

  function toggleActive(slug: string) {
    const next = new Set(active.value)
    if (next.has(slug)) next.delete(slug)
    else next.add(slug)
    active.value = next
    saveActive(currentSessionId.value, next)
    // eslint-disable-next-line no-console
    console.log(
      "[skills] toggleActive",
      slug,
      "sessionId=",
      currentSessionId.value,
      "size=",
      next.size,
      "items=",
      JSON.stringify([...next]),
    )
  }

  function clearActive() {
    active.value = new Set()
    saveActive(currentSessionId.value, active.value)
  }

  async function setEnabled(slug: string, value: boolean) {
    const updated = await api.setSkillEnabled(slug, value)
    replace(updated)
    if (!value) {
      const next = new Set(active.value)
      next.delete(slug)
      active.value = next
      saveActive(currentSessionId.value, next)
    }
  }

  async function remove(slug: string) {
    await api.deleteSkill(slug)
    items.value = items.value.filter((s) => s.slug !== slug)
    const next = new Set(active.value)
    next.delete(slug)
    active.value = next
    saveActive(currentSessionId.value, next)
  }

  async function importFolder(source: string) {
    const created = await api.importSkillFolder(source)
    upsert(created)
    return created
  }

  async function importZip(name: string, blob: Blob) {
    const created = await api.importSkillZip(name, blob)
    upsert(created)
    return created
  }

  function replace(skill: Skill) {
    const idx = items.value.findIndex((s) => s.slug === skill.slug)
    if (idx === -1) items.value.push(skill)
    else items.value[idx] = skill
  }

  function upsert(skill: Skill) {
    const idx = items.value.findIndex((s) => s.slug === skill.slug)
    if (idx === -1) items.value = [...items.value, skill]
    else items.value = items.value.map((s) => (s.slug === skill.slug ? skill : s))
  }

  return {
    items,
    enabled,
    loading,
    error,
    currentSessionId,
    active,
    setCurrentSession,
    refresh,
    isActive,
    toggleActive,
    clearActive,
    setEnabled,
    remove,
    importFolder,
    importZip,
  }
})
