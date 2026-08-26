import { computed, ref } from "vue"
import { defineStore } from "pinia"
import { api, type MCPServer } from "../api/client"

const LS_PREFIX = "mhc.mcp.active."

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

export const useMCPsStore = defineStore("mcps", () => {
  const items = ref<MCPServer[]>([])
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
      items.value = await api.listMCPs()
      // Drop active slugs that no longer exist or were disabled.
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
  }

  function clearActive() {
    active.value = new Set()
    saveActive(currentSessionId.value, active.value)
  }

  async function setEnabled(slug: string, value: boolean) {
    const updated = await api.setMCPEnabled(slug, value)
    replace(updated)
    if (!value) {
      const next = new Set(active.value)
      next.delete(slug)
      active.value = next
      saveActive(currentSessionId.value, next)
    }
  }

  async function remove(slug: string) {
    await api.deleteMCP(slug)
    items.value = items.value.filter((s) => s.slug !== slug)
    const next = new Set(active.value)
    next.delete(slug)
    active.value = next
    saveActive(currentSessionId.value, next)
  }

  async function upsert(body: Parameters<typeof api.upsertMCP>[0]) {
    const created = await api.upsertMCP(body)
    upsertItem(created)
    return created
  }

  function replace(s: MCPServer) {
    const idx = items.value.findIndex((x) => x.slug === s.slug)
    if (idx === -1) items.value.push(s)
    else items.value[idx] = s
  }

  function upsertItem(s: MCPServer) {
    const idx = items.value.findIndex((x) => x.slug === s.slug)
    if (idx === -1) items.value = [...items.value, s]
    else items.value = items.value.map((x) => (x.slug === s.slug ? s : x))
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
    upsert,
    upsertItem,
    replace,
  }
})