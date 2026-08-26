// Per-session SSE stream bus.
//
// Owns the live EventSource for each running chat session so that
// multiple sessions can stream in parallel AND the active session
// can change without cancelling the others. ChatView subscribes to
// events for the session it currently shows; on session switch it
// unsubscribes (the stream keeps running) and resubscribes on
// switch-back, picking up any chunks that arrived while it was
// away.
//
// The bus is also the place where assistant content + tool call
// state accumulate. ChatView reads final-ish state via the
// subscribe callback so it doesn't have to manage any streaming
// state itself.

import { defineStore } from "pinia"
import { ref } from "vue"
import { api, streamChat, type ChatMessage, type ChatRequest, type StreamEvent } from "../api/client"

export type ToolCallStatus = "pending" | "executing" | "success" | "error"

/** One entry in the ordered timeline of an assistant message. The
 *  model's reply is NOT one flat text blob with tools afterwards —
 *  it interleaves: text → tool call → text → tool call... This
 *  timeline preserves the exact chronological order so the UI can
 *  render thinking, prose and capsules in the sequence they
 *  happened, instead of dumping all capsules below the text. */
export type MessageSegment =
  | { kind: "text"; content: string }
  | { kind: "thinking"; content: string }
  | { kind: "tool"; call: ToolCallState }

export interface ToolCallState {
  call_id: string
  /** "mcp" for MCP-namespaced calls, "tool" for plain Tool calls.
   *  Drives the capsule icon / colour in the renderer. */
  kind: "mcp" | "tool"
  name: string  // "<mcp-slug>::<tool-name>" OR "<tool-name>"
  args: Record<string, unknown>
  result?: string
  error?: string
  ok?: boolean
  /** ``true`` when the backend's ``cancelled`` flag tripped while
   *  the call was in flight; lets the UI show a distinct
   *  "cancelled" state instead of just "error". */
  cancelled?: boolean
  status: ToolCallStatus
  /** Epoch ms when the tool_start event landed. Drives the live
   *  elapsed-time counter in the capsule. Set on tool_start. */
  startedAt?: number
  /** Final duration in ms after the call completes. Set on
   *  tool_end so the capsule can show "ran in 3.2s". */
  durationMs?: number
}

export interface SessionStreamState {
  streaming: boolean
  cancelled: boolean
  error: string | null
  /** The assistant message we're currently filling. Empty string when
   *  no stream is active. The session store also persists this id so a
   *  reload can attribute the partial content back to the same node. */
  assistantMessageId: string
  /** Accumulated plain text content. NOT cleared on subscribe — when
   *  the user switches back to a running session, they pick up the
   *  latest accumulated text rather than starting from zero. */
  assistantContent: string
  /** Ordered timeline of the assistant message: text runs and tool
   *  calls in the exact order the SSE stream delivered them. This is
   *  what the UI renders; see ``MessageSegment``. */
  segments: MessageSegment[]
  /** Per-session tool call log. Newest at the end. */
  toolCalls: ToolCallState[]
  /** Token usage from the most recent ``done`` event. */
  usage: Record<string, unknown> | null
  /** Monotonic seq counter for gap detection. Backend tags every
   *  event with seq=1,2,3... so a subscriber that sees a gap can
   *  mark the stream as out-of-order (rare, mostly means a new
   *  request replaced the old one). */
  lastSeq: number
  /** True while one or more tool calls are in flight between the
   *  matching ``execution_start`` / ``execution_end`` events. */
  executionInFlight: boolean
}

interface InternalHandle {
  state: SessionStreamState
  controller: AbortController | null
  listeners: Set<(ev: StreamEvent) => void>
  /** Per-session message baseline for persistence, captured at
   *  ``start()`` time — the moment the caller's ``messages.value``
   *  is guaranteed to belong to THIS session. Persisting reads ONLY
   *  this + the bus's own live state. Never a closure over the
   *  shared ``messages.value`` array: that array is replaced on
   *  every session switch, so reading it at persist time would
   *  write session B's history into session A's disk record. */
  persistBase: ChatMessage[]
}

const emptyState = (): SessionStreamState => ({
  streaming: false,
  cancelled: false,
  error: null,
  assistantMessageId: "",
  assistantContent: "",
  segments: [],
  toolCalls: [],
  usage: null,
  lastSeq: 0,
  /** Set while one or more tool calls are in flight between
   *  ``execution_start`` and ``execution_end``. The UI shows an
   *  "execution in progress" indicator while this is true. */
  executionInFlight: false,
})

export const useSessionStreamsStore = defineStore("sessionStreams", () => {
  /** Completion listener (set by the app shell). Called once when a
   *  session's stream ends for any reason (done / error / cancel).
   *  The shell uses it to raise a "session finished" toast and lets
   *  the user navigate around other sessions meanwhile — the stream
   *  itself keeps running in the background and never depends on
   *  anyone being subscribed to it. */
  let onComplete: ((sessionId: string) => void) | null = null
  const handles = ref(new Map<string, InternalHandle>())
  /** Reverse-index from assistantMessageId -> sessionId so callers
   *  that only know the message id can find the session. */
  const assistantToSession = ref(new Map<string, string>())

  function _ensure(sessionId: string): InternalHandle {
    let h = handles.value.get(sessionId)
    if (!h) {
      h = {
        state: emptyState(),
        controller: null,
        listeners: new Set(),
        persistBase: [],
      }
      handles.value.set(sessionId, h)
    }
    return h
  }

  function getState(sessionId: string): SessionStreamState {
    return _ensure(sessionId).state
  }

  function isStreaming(sessionId: string): boolean {
    return _ensure(sessionId).state.streaming
  }

  function subscribe(
    sessionId: string,
    listener: (ev: StreamEvent) => void,
  ): () => void {
    const h = _ensure(sessionId)
    h.listeners.add(listener)
    return () => {
      h.listeners.delete(listener)
    }
  }

  function _emit(sessionId: string, ev: StreamEvent) {
    const h = handles.value.get(sessionId)
    if (!h) return
    h.listeners.forEach((cb) => {
      try {
        cb(ev)
      } catch (e) {
        console.error("[sessionStreams] listener error:", e)
      }
    })
  }

  /** Compose the canonical on-disk shape for a session from its
   *  persist baseline + the bus's live assistant state. The live
   *  message is included only after the stream ends (``streaming``
   *  false) so reloads see the finished reply; mid-stream debounced
   *  persists keep the baseline only, same as the old
   *  ``filter(!pending)`` behaviour.
   *
   *  A cancelled run persists its partial content (what the user
   *  already consumed) plus the ``cancelled`` flag, so a reloaded
   *  session shows the SAME partial reply the live view did — never
   *  a wiped bubble. */
  function _composePersist(h: InternalHandle): ChatMessage[] {
    const out = [...h.persistBase]
    if (!h.state.streaming) {
      const hasLive =
        h.state.assistantContent !== "" ||
        h.state.toolCalls.length > 0 ||
        h.state.segments.length > 0
      if (hasLive) {
        out.push({
          role: "assistant",
          content: h.state.assistantContent,
          tool_calls:
            h.state.toolCalls.length > 0 ? h.state.toolCalls : undefined,
          segments:
            h.state.segments.length > 0 ? h.state.segments : undefined,
          cancelled: h.state.cancelled || undefined,
        })
      }
    }
    return out
  }

  /** Persist a session's canonical message list into the session
   *  store. Called right after ``start()`` (so the user's message
   *  lands before any UI switch could orphan it), on terminal
   *  events (done / cancelled / error), and on a debounced timer
   *  during streaming so a window close mid-stream doesn't lose
   *  everything. Best-effort: errors are swallowed because the
   *  next terminal event will retry. */
  async function _persist(sessionId: string, h: InternalHandle) {
    if (!sessionId) return
    await api.updateSession(sessionId, {
      messages: _composePersist(h),
    })
  }

  /** Open a new SSE stream for ``sessionId``. If one is already
   *  running, it's cancelled first (the registry on the backend will
   *  also cancel the previous run on its side).
   *
   *  ``baseMessages`` is the session's full message list EVALUATED
   *  NOW — at send time the caller's ``messages.value`` is
   *  guaranteed to be this session's array (it just pushed the
   *  user message onto it). Persistence never reads
   *  ``messages.value`` again: the bus keeps this baseline
   *  per-session and appends its own live assistant state to it,
   *  so parallel sessions stream and persist independently no
   *  matter which one the UI is showing. */
  async function start(
    sessionId: string,
    payload: ChatRequest,
    assistantMessageId: string,
    /** Full composed history for this session INCLUDING the new
     *  user message, excluding the just-pushed pending assistant
     *  placeholder (the bus adds that from its own live state). */
    baseMessages: ChatMessage[],
  ): Promise<void> {
    if (!sessionId) return
    const h = _ensure(sessionId)
    if (h.state.streaming) {
      // Cancel locally; the backend will see the cancel too via the
      // cancel endpoint, but more importantly the new request will
      // replace the old stream on the registry side.
      h.controller?.abort()
      h.state.streaming = false
      h.state.cancelled = true
    }
    h.state = emptyState()
    h.state.streaming = true
    h.state.assistantMessageId = assistantMessageId
    h.persistBase = baseMessages
    assistantToSession.value.set(assistantMessageId, sessionId)

    const controller = new AbortController()
    h.controller = controller

    const payloadWithSession = {
      ...payload,
      session_id: sessionId,
      assistant_message_id: assistantMessageId,
    }

    // Land the user's message on disk immediately. If the user
    // switches away before the first chunk (LLM latency), the
    // session must still show its own instruction on return — the
    // debounced mid-stream persists wouldn't fire until a chunk.
    void _persist(sessionId, h).catch(() => {})

    const persistDebounced = _debounce(() => {
      void _persist(sessionId, h).catch(() => {})
    }, 1500)

    try {
      for await (const ev of streamChat(payloadWithSession, controller.signal)) {
        if (controller.signal.aborted) break
        // Track seq for gap detection
        const seq = (ev as unknown as { seq?: number }).seq
        if (typeof seq === "number") {
          if (seq !== h.state.lastSeq + 1 && h.state.lastSeq > 0) {
            console.warn(
              `[sessionStreams] seq gap session=${sessionId} ` +
                `expected ${h.state.lastSeq + 1}, got ${seq}`,
            )
          }
          h.state.lastSeq = seq
        }

        if (ev.type === "chunk") {
          h.state.assistantContent += ev.content
          // Append to the in-progress text run (or start one after a
          // tool segment) so the timeline stays chronological.
          const last = h.state.segments[h.state.segments.length - 1]
          if (last && last.kind === "text") {
            last.content += ev.content
          } else {
            h.state.segments.push({ kind: "text", content: ev.content })
          }
          persistDebounced()
        } else if (ev.type === "reasoning") {
          // A reasoning delta: accumulate into a "thinking" block that
          // sits in the timeline exactly where the model thought
          // (almost always right before the reply text it led to).
          const last = h.state.segments[h.state.segments.length - 1]
          if (last && last.kind === "thinking") {
            last.content += ev.content
          } else {
            h.state.segments.push({ kind: "thinking", content: ev.content })
          }
          persistDebounced()
        } else if (ev.type === "execution_start") {
          h.state.executionInFlight = true
        } else if (ev.type === "execution_end") {
          h.state.executionInFlight = false
        } else if (ev.type === "tool_args_start") {
          // Model just started emitting a tool call — args
          // haven't finished yet. Render a "pending" capsule
          // so the user sees the call start immediately, not
          // only once the tool is about to execute.
          const call: ToolCallState = {
            call_id: ev.call_id,
            kind: ev.kind,
            name: ev.name || "tool_call",
            args: {},
            status: "pending",
          }
          h.state.toolCalls.push(call)
          h.state.segments.push({ kind: "tool", call })
          persistDebounced()
        } else if (ev.type === "tool_args_delta") {
          // Args still streaming in — keep accumulating into
          // the pending capsule's rawArgs so the popover can
          // show the half-formed JSON if the user opens it.
          const tc = h.state.toolCalls.find((t) => t.call_id === ev.call_id)
          if (tc) {
            tc.args = tc.args || {}
            tc.args.__raw__ =
              ((tc.args.__raw__ as string | undefined) ?? "") +
              ev.arguments_chunk
          }
          persistDebounced()
        } else if (ev.type === "tool_start") {
          // Args complete — transition any pending capsule we
          // created on tool_args_start into the executing state.
          // Falls back to creating a fresh executing call if
          // the provider never streamed the args (e.g.
          // non-streaming models).
          const existing = h.state.toolCalls.find((t) => t.call_id === ev.call_id)
          if (existing) {
            existing.name = ev.name
            existing.kind = ev.kind
            existing.args = ev.args
            existing.status = "executing"
          } else {
            const call: ToolCallState = {
              call_id: ev.call_id,
              kind: ev.kind,
              name: ev.name,
              args: ev.args,
              status: "executing",
            }
            h.state.toolCalls.push(call)
            h.state.segments.push({ kind: "tool", call })
          }
          persistDebounced()
        } else if (ev.type === "tool_progress") {
          // Bundled / local tools yield one chunk today; we treat
          // each chunk as an append on a half-formed result string.
          // Streaming tools will fill this in later.
          const tc = h.state.toolCalls.find((t) => t.call_id === ev.call_id)
          if (tc) tc.result = (tc.result ?? "") + ev.chunk
          const seg = h.state.segments.find(
            (s) => s.kind === "tool" && s.call.call_id === ev.call_id,
          )
          if (seg && seg.kind === "tool") {
            seg.call.result = (seg.call.result ?? "") + ev.chunk
          }
        } else if (ev.type === "tool_end") {
          const tc = h.state.toolCalls.find((t) => t.call_id === ev.call_id)
          if (tc) {
            tc.result = ev.result
            tc.error = ev.error ?? undefined
            tc.ok = ev.ok
            tc.cancelled = ev.cancelled ?? false
            tc.status = ev.ok ? "success" : "error"
          }
          const seg = h.state.segments.find(
            (s) => s.kind === "tool" && s.call.call_id === ev.call_id,
          )
          if (seg && seg.kind === "tool") {
            const c = seg.call
            c.result = ev.result
            c.error = ev.error ?? undefined
            c.ok = ev.ok
            c.cancelled = ev.cancelled ?? false
            c.status = ev.ok ? "success" : "error"
          }
          persistDebounced()
        } else if (ev.type === "cancelled") {
          h.state.cancelled = true
          h.state.streaming = false
        } else if (ev.type === "done") {
          h.state.usage = ev.usage ?? null
          h.state.streaming = false
        } else if (ev.type === "error") {
          h.state.error = ev.message
          h.state.streaming = false
        }

        _emit(sessionId, ev)
      }
    } catch (e) {
      if (!controller.signal.aborted) {
        h.state.error = e instanceof Error ? e.message : String(e)
        h.state.streaming = false
      }
    } finally {
      h.state.streaming = false
      h.controller = null
      assistantToSession.value.delete(assistantMessageId)
      // Final persist on terminal event.
      void _persist(sessionId, h).catch((e) => {
        console.error("[sessionStreams] persist failed:", e)
      })
      // One-shot completion signal for the app shell (toast on done).
      onComplete?.(sessionId)
    }
  }

  async function cancel(sessionId: string): Promise<void> {
    const h = handles.value.get(sessionId)
    if (!h) return
    h.controller?.abort()
    h.state.streaming = false
    h.state.cancelled = true
    // Synthesise a ``cancelled`` event for our subscribers so the
    // Vue side updates ``m.pending = false`` BEFORE the SSE loop's
    // ``finally`` calls ``_persist`` — otherwise the assistant
    // message stays ``pending: true`` and gets filtered out of the
    // persisted shape, leaving the user with a half-finished
    // assistant turn on reload. The backend's own ``cancelled``
    // event would normally do this, but we aborted the SSE
    // connection before it arrived.
    _emit(sessionId, {
      type: "cancelled",
      session_id: sessionId,
      seq: 0,
    })
    // Tell the backend to stop too — the chunk loop will emit
    // ``cancelled`` and close. Without this the LLM provider would
    // keep generating until the model itself stops.
    try {
      await api.cancelChat(sessionId)
    } catch (e) {
      console.warn("[sessionStreams] cancel backend call failed:", e)
    }
  }

  async function cancelAll(): Promise<void> {
    const active = [...handles.value.entries()].filter(
      ([, h]) => h.state.streaming,
    )
    await Promise.all(active.map(([sid]) => cancel(sid)))
  }

  /** Called by the renderer on window close. Best-effort: asks the
   *  backend to cancel each running stream, then waits up to
   *  ``timeoutMs`` ms for the for-await loops to settle so the
   *  terminal persist call has a chance to flush to disk. After
   *  that the process can exit. */
  async function flush(timeoutMs = 2000): Promise<void> {
    const active = [...handles.value.entries()].filter(
      ([, h]) => h.state.streaming,
    )
    if (active.length === 0) return
    active.forEach(([, h]) => h.controller?.abort())
    await Promise.all(
      active.map(([sid]) => api.cancelChat(sid).catch(() => {})),
    )
    // Give the persist callbacks time to land. We don't await them
    // individually — the bus's debounced write fires ~1500 ms after
    // the last chunk, so timeout must exceed that to guarantee the
    // user doesn't lose the most recent content.
    await new Promise((r) => setTimeout(r, timeoutMs))
  }

  function reset(sessionId: string) {
    const h = handles.value.get(sessionId)
    if (!h) return
    h.controller?.abort()
    h.state = emptyState()
  }

  function setOnComplete(cb: ((sessionId: string) => void) | null) {
    onComplete = cb
  }

  return {
    handles,
    getState,
    isStreaming,
    subscribe,
    start,
    cancel,
    cancelAll,
    flush,
    reset,
    setOnComplete,
  }
})

function _debounce<T extends (...args: unknown[]) => void>(fn: T, ms: number): T {
  let timer: ReturnType<typeof setTimeout> | null = null
  return ((...args: unknown[]) => {
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => fn(...args), ms)
  }) as T
}