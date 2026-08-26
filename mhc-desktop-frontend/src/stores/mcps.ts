import { computed, ref } from "vue"
import { defineStore } from "pinia"
import { api, type MCPServer } from "../api/client"

// MCP now follows the same rule as skills and tools: there is no
// per-session "active" concept. Every enabled server is injected
// into every user message, and enable/disable lives in the /mcp
// configuration page (mcps.setEnabled). The old per-session
// localStorage "active" set is gone.

export const useMCPsStore = defineStore("mcps", () => {
  const items = ref<MCPServer[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  const enabled = computed(() => items.value.filter((s) => s.enabled))

  async function refresh() {
    loading.value = true
    error.value = null
    try {
      items.value = await api.listMCPs()
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
    } finally {
      loading.value = false
    }
  }

  async function setEnabled(slug: string, value: boolean) {
    const updated = await api.setMCPEnabled(slug, value)
    replace(updated)
  }

  async function remove(slug: string) {
    await api.deleteMCP(slug)
    items.value = items.value.filter((s) => s.slug !== slug)
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
    refresh,
    setEnabled,
    remove,
    upsert,
    upsertItem,
    replace,
  }
})