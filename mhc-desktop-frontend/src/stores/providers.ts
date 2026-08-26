// Pinia store for providers. Models are configured through providers,
// so this is the data source for both the provider list inside the
// Models page and the model picker in the chat.

import { defineStore } from "pinia"
import { ref } from "vue"
import { api, type Provider } from "../api/client"

export const useProvidersStore = defineStore("providers", () => {
  const items = ref<Provider[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function refresh() {
    loading.value = true
    error.value = null
    try {
      items.value = await api.listProviders()
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
    } finally {
      loading.value = false
    }
  }

  async function create(body: Partial<Provider> & { name: string }) {
    const created = await api.createProvider(body)
    items.value = [...items.value, created]
    return created
  }

  async function remove(name: string) {
    await api.deleteProvider(name)
    items.value = items.value.filter((p) => p.name !== name)
  }

  async function setEnabled(name: string, enabled: boolean) {
    const updated = await api.updateProvider(name, { enabled })
    const idx = items.value.findIndex((p) => p.name === name)
    if (idx >= 0) items.value[idx] = updated
    return updated
  }

  async function update(name: string, body: Partial<Provider> & { name: string }) {
    const updated = await api.updateProvider(name, body)
    const idx = items.value.findIndex((p) => p.name === name)
    if (idx >= 0) items.value[idx] = updated
    return updated
  }

  return { items, loading, error, refresh, create, remove, setEnabled, update }
})