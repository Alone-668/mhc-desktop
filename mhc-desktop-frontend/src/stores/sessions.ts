// Pinia store for chat sessions.

import { defineStore } from "pinia"
import { ref } from "vue"
import { api, type ChatMessage, type Session, type SessionSummary } from "../api/client"

export const useSessionsStore = defineStore("sessions", () => {
  const items = ref<SessionSummary[]>([])
  const currentId = ref<string | null>(null)
  const current = ref<Session | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function refresh() {
    loading.value = true
    error.value = null
    try {
      items.value = await api.listSessions()
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
    } finally {
      loading.value = false
    }
  }

  async function create() {
    const sess = await api.createSession({})
    items.value = [sess, ...items.value]
    await select(sess.id)
    return sess
  }

  async function select(id: string) {
    currentId.value = id
    current.value = await api.getSession(id)
  }

  async function clear() {
    currentId.value = null
    current.value = null
  }

  async function remove(id: string) {
    await api.deleteSession(id)
    items.value = items.value.filter((s) => s.id !== id)
    if (currentId.value === id) {
      await clear()
    }
  }

  async function removeMany(ids: string[]) {
    if (!ids.length) return 0
    await api.deleteManySessions(ids)
    const set = new Set(ids)
    items.value = items.value.filter((s) => !set.has(s.id))
    if (currentId.value && set.has(currentId.value)) {
      await clear()
    }
    return ids.length
  }

  async function clearAll() {
    const r = await api.clearSessions()
    items.value = []
    await clear()
    return r.removed
  }

  async function rename(id: string, title: string) {
    const updated = await api.renameSession(id, title)
    const idx = items.value.findIndex((s) => s.id === id)
    if (idx >= 0) {
      items.value[idx] = {
        ...items.value[idx],
        title: updated.title,
        updated_at: updated.updated_at,
      }
    }
    if (currentId.value === id && current.value) {
      current.value = { ...current.value, title: updated.title }
    }
    return updated
  }

  /** Apply an auto-generated title to a session in the sidebar.
   *
   *  Called after the first user message of a session lands and
   *  the backend summarises it into a Chinese title (≤10 chars).
   *  We splice it into ``items`` so the sidebar reflects the new
   *  title without a full ``refresh()`` round-trip, and update
   *  ``current`` if the active session is the one being titled. */
  function applyAutoTitle(id: string, title: string) {
    const idx = items.value.findIndex((s) => s.id === id)
    if (idx >= 0) {
      items.value[idx] = {
        ...items.value[idx],
        title,
        updated_at: new Date().toISOString(),
      }
    }
    if (currentId.value === id && current.value) {
      current.value = { ...current.value, title }
    }
  }

  return {
    items,
    currentId,
    current,
    loading,
    error,
    refresh,
    create,
    select,
    clear,
    remove,
    removeMany,
    clearAll,
    rename,
    applyAutoTitle,
  }
})