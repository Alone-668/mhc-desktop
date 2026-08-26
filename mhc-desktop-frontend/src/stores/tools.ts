// Pinia store for Tools (the third concept — local / script /
// remote). Mirrors the Skills and MCPs stores: items + enabled
// view + per-session "active" set + actions to toggle. The
// installer ships no built-in tools; everything here is either
// hand-imported or bulk-imported from a content pack.

import { defineStore } from "pinia"
import { ref, computed } from "vue"
import {
  api,
  type Tool,
  type ToolExport,
  type ToolKind,
} from "../api/client"

// Tools every conversation gets by default, so the assistant can
// run commands and work with files without the user toggling them
// on first. Only slugs that actually exist AND are enabled are
// seeded — a missing/disabled tool is never shown or sent.
export const useToolsStore = defineStore("tools", () => {
  const items = ref<Tool[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  const enabledTools = computed(() => items.value.filter((t) => t.enabled))

  async function refresh() {
    loading.value = true
    error.value = null
    try {
      items.value = await api.listTools()
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
    } finally {
      loading.value = false
    }
  }


  async function create(body: Partial<Tool> & { name: string; kind?: ToolKind }) {
    const t = await api.createTool(body)
    items.value = [t, ...items.value]
    return t
  }

  async function update(slug: string, body: Partial<Tool>) {
    const t = await api.updateTool(slug, body)
    items.value = items.value.map((x) => (x.slug === slug ? t : x))
    return t
  }

  async function remove(slug: string) {
    await api.deleteTool(slug)
    items.value = items.value.filter((t) => t.slug !== slug)
  }

  async function setEnabled(slug: string, enabled: boolean) {
    const t = await api.setToolEnabled(slug, enabled)
    items.value = items.value.map((x) => (x.slug === slug ? t : x))
    return t
  }

  async function importSource(body: {
    slug?: string
    name?: string
    description?: string
    parameters?: Record<string, unknown>
    source: string
    overwrite?: boolean
    origin?: string
    source_path?: string
  }) {
    const t = await api.importToolSource(body)
    items.value = items.value.filter((x) => x.slug !== t.slug)
    items.value = [t, ...items.value]
    return t
  }

  async function fetchExport(slug: string): Promise<ToolExport> {
    const r = await fetch(api.exportToolUrl(slug))
    if (!r.ok) throw new Error(`export ${slug} ${r.status}`)
    return (await r.json()) as ToolExport
  }

  function nameFor(slug: string): string {
    return items.value.find((t) => t.slug === slug)?.name ?? slug
  }

  return {
    items,
    loading,
    error,
    enabledTools,
    refresh,
    create,
    update,
    remove,
    setEnabled,
    importSource,
    fetchExport,
    nameFor,
  }
})