// Tiny imperative API for the ConfirmModal singleton. Call sites do:
//
//   import { ask } from "../lib/confirm"
//   const ok = await ask({ title, message, tone: "danger" })
//   if (!ok) return
//
// Backed by a module-scoped reactive object so any view (or hook)
// can fire a confirm without threading props around the tree. The
// actual <ConfirmModal /> lives once in App.vue.
import { reactive } from "vue"

export type ConfirmTone = "default" | "danger"

export interface ConfirmOpts {
  title?: string
  message: string
  tone?: ConfirmTone
  confirmLabel?: string
  cancelLabel?: string
}

interface ConfirmState {
  open: boolean
  title?: string
  message: string
  tone: ConfirmTone
  confirmLabel?: string
  cancelLabel?: string
  // Resolve fn for the in-flight ask() promise.
  _resolve: ((ok: boolean) => void) | null
}

const state = reactive<ConfirmState>({
  open: false,
  message: "",
  tone: "default",
  _resolve: null,
})

// Methods live on the same reactive object so the modal can call
// ``state.confirm()`` / ``state.cancel()`` directly via ``useConfirm()``.
function settle(ok: boolean) {
  if (!state.open) return
  const r = state._resolve
  state._resolve = null
  state.open = false
  // Clear so a stale toast doesn't briefly flash on next open.
  state.message = ""
  state.title = undefined
  r?.(ok)
}

;(state as ConfirmState & { confirm: () => void; cancel: () => void }).confirm =
  () => settle(true)
;(state as ConfirmState & { confirm: () => void; cancel: () => void }).cancel =
  () => settle(false)

export function useConfirm() {
  return state as ConfirmState & { confirm: () => void; cancel: () => void }
}

export function ask(opts: ConfirmOpts): Promise<boolean> {
  // Refuse to stack dialogs — if one is already open, treat as
  // cancel for the new request. Better than racing two modals.
  if (state.open) return Promise.resolve(false)
  state.title = opts.title
  state.message = opts.message
  state.tone = opts.tone ?? "default"
  state.confirmLabel = opts.confirmLabel
  state.cancelLabel = opts.cancelLabel
  return new Promise<boolean>((resolve) => {
    state._resolve = resolve
    state.open = true
  })
}

export function closeConfirm(ok: boolean) {
  settle(ok)
}