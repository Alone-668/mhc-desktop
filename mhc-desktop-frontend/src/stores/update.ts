import { defineStore } from "pinia"
import { ref } from "vue"

/** Subset of the main-process update snapshot we care about. `forceTier1`
 *  is filtered out in snapshotForRenderer() so it never crosses IPC. */
export interface UpdateStatus {
  state: string
  releasedAt?: string
  available?: { spa?: string; content_packs?: string; backend?: string }
  error?: string
  progressBytes?: number
  progressTotal?: number
  channel?: string
}

export const useUpdateStore = defineStore("update", () => {
  const status = ref<UpdateStatus>({ state: "idle" })
  const busy = ref(false)
  const lastError = ref<string | null>(null)

  /** Call any preload method that returns a fresh status snapshot.
   *  All three actions (checkNow / install / applyNow) follow the same
   *  pattern: set busy → invoke → set status → catch → store error. */
  async function call(fn: () => Promise<UpdateStatus>): Promise<void> {
    if (!window.mhc?.update) return
    busy.value = true
    lastError.value = null
    try {
      status.value = await fn()
    } catch (e) {
      lastError.value = e instanceof Error ? e.message : String(e)
    } finally {
      busy.value = false
    }
  }

  async function refresh() {
    if (!window.mhc?.update) return
    try {
      status.value = await window.mhc.update.getStatus()
    } catch (e) {
      lastError.value = e instanceof Error ? e.message : String(e)
    }
  }

  // Captured locally so TS sees the optional chain as resolved inside
  // each closure; otherwise `window.mhc!.update.X` still complains.
  const api = window.mhc?.update
  const checkNow = () => call(() => api!.checkNow())
  const install = () => call(() => api!.install())
  const applyNow = () => call(() => api!.applyNow())

  /** Subscribe to live updates from the main process. Returns the
   *  unsubscribe handle — callers MUST call it from onUnmounted to
   *  avoid accumulating IPC listeners across settings navigation. */
  function subscribe(): () => void {
    if (!window.mhc?.update) return () => undefined
    return window.mhc.update.onState((s) => {
      status.value = s
    })
  }

  return { status, busy, lastError, refresh, checkNow, install, applyNow, subscribe }
})
