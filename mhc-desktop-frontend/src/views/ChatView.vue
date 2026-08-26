<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue"
import { useProvidersStore } from "../stores/providers"
import { useSessionsStore } from "../stores/sessions"
import { useSessionStreamsStore } from "../stores/sessionStreams"
import { useSkillsStore } from "../stores/skills"
import { useMCPsStore } from "../stores/mcps"
import { useToolsStore } from "../stores/tools"
import { api, type ChatMessage, type LLMToolCall } from "../api/client"
import Icon from "../components/Icon.vue"
import MarkdownView from "../components/MarkdownView.vue"
import ToolCallCapsule from "../components/ToolCallCapsule.vue"
import ThinkingBlock from "../components/ThinkingBlock.vue"
import VirtualMessageList from "../components/VirtualMessageList.vue"
import { t } from "../i18n"

const store = useProvidersStore()
const sessions = useSessionsStore()
const streams = useSessionStreamsStore()
const skills = useSkillsStore()
const mcps = useMCPsStore()
const tools = useToolsStore()

/** Persistent message history for the active session. Loaded from
 *  disk on session switch; updated live by the bus subscription. */
interface LocalMessage extends ChatMessage {
  id: string
  pending?: boolean
  error?: string
  /** ``true`` when THIS assistant message was cancelled mid-stream
   *  (user pressed stop). Persisted alongside the partial content
   *  so a reloaded session shows the same state as the live view. */
  cancelled?: boolean
  tool_calls?: import("../stores/sessionStreams").ToolCallState[]
  segments?: import("../api/client").MessageSegmentPersistence[]
  tools?: string[]
}

const selectedModelKey = ref<string>("")
const input = ref<string>("")
const messages = ref<LocalMessage[]>([])
/** Max number of files the user can attach at once. Past this
 *  count, additional selections / drops are silently dropped
 *  (the chip row already shows the cap; we don't pop a modal). */
const MAX_FILES = 5
/** Files the user has attached but not yet sent. Each entry carries
 *  the absolute path (Electron's File.path extension) so the
 *  backend can hand it to a tool. Never includes the bytes. */
const attachedFiles = ref<
  Array<{ name: string; path: string; size: number; type: string }>
>([])
/** Per-message "is the long-tool-chain summary expanded" state.
   Initially true for short chains, false for long ones — the user
   can re-expand a collapsed chain with one click. Keyed by message
   id. */
const toolChainOpen = ref<Record<string, boolean>>({})
const expanded = ref(false)
const modelOpen = ref(false)
const modelPickerEl = ref<HTMLElement | null>(null)
const composerEl = ref<HTMLTextAreaElement | null>(null)
const scrollerEl = ref<InstanceType<typeof VirtualMessageList> | null>(null)
const stickToBottom = ref(true)
let unsubBus: (() => void) | null = null

const enabledProviders = computed(() =>
  store.items.filter((p) => p.enabled !== false),
)
const currentProviderName = computed(() => selectedModelKey.value.split("::")[0] ?? "")
const currentModelCode = computed(() => selectedModelKey.value.split("::")[1] ?? "")
const currentProvider = computed(() =>
  store.items.find((p) => p.name === currentProviderName.value),
)
const currentModelLabel = computed(() => {
  if (!selectedModelKey.value) return ""
  const [pname, mcode] = selectedModelKey.value.split("::")
  const provider = store.items.find((p) => p.name === pname)
  if (!provider) return mcode || pname
  const model = provider.models.find((m) => m.code === mcode)
  if (model?.display_name) return model.display_name
  return mcode || pname
})

const activeStream = computed(() => {
  const id = sessions.currentId
  if (!id) return null
  return streams.getState(id)
})
const streaming = computed(() => activeStream.value?.streaming ?? false)
const liveAssistantId = computed(() => activeStream.value?.assistantMessageId ?? "")
const streamingError = computed(() => {
  // True while the live assistant message already carries an error
  // string; in that case the streaming bar is redundant and the
  // error message in the bubble is the right surface.
  const id = liveAssistantId.value
  if (!id) return false
  const m = messages.value.find((x) => x.id === id)
  return Boolean(m?.error)
})

const contextUsage = computed(() => {
  const u = activeStream.value?.usage
  if (!u) return null
  const prompt = Number(u.prompt_tokens ?? u.input_tokens ?? 0) || 0
  const completion = Number(u.completion_tokens ?? u.output_tokens ?? 0) || 0
  const total = Number(u.total_tokens ?? prompt + completion) || 0
  return { prompt, completion, total, raw: u }
})
const modelMaxContext = computed(() => {
  const p = currentProvider.value
  if (!p) return 0
  const m = p.models.find((m) => m.code === currentModelCode.value)
  return m?.max_context ?? p.max_context_default ?? 0
})
const contextRatio = computed(() => {
  if (!contextUsage.value || !modelMaxContext.value) return 0
  return Math.min(1, contextUsage.value.total / modelMaxContext.value)
})

// Color threshold for the context ring.
//   ratio < 0.4   → green (plenty of room)
//   0.4 ≤ ratio < 0.7 → yellow (warm)
//   ratio ≥ 0.7   → red (close to / over the limit)
const ctxRingClass = computed(() => {
  const r = contextRatio.value
  if (r >= 0.7) return "ctx-warn-high"
  if (r >= 0.4) return "ctx-warn-mid"
  return "ctx-warn-low"
})
// Stroke-dasharray on a circle of r=15.9155 is ~100, so this reads
// directly as a percent.
const ctxRingDasharray = computed(() => {
  const pct = Math.min(1, contextRatio.value) * 100
  return `${pct} ${100 - pct}`
})

onMounted(async () => {
  await Promise.all([
    store.refresh(),
    sessions.refresh(),
    skills.refresh(),
    mcps.refresh(),
    tools.refresh(),
  ])
  if (!selectedModelKey.value && enabledProviders.value.length > 0) {
    const p = enabledProviders.value[0]
    const m = p.models[0]?.code ?? p.default_model
    if (m) selectedModelKey.value = `${p.name}::${m}`
  }
  if (sessions.items.length > 0 && !sessions.currentId) {
    await sessions.select(sessions.items[0].id)
  }
  skills.setCurrentSession(sessions.currentId)
  mcps.setCurrentSession(sessions.currentId)
  tools.setCurrentSession(sessions.currentId)
  // Re-subscribe to the initial session if the store already picked
  // one (watch with immediate:true handles this in the next tick).
})

onBeforeUnmount(async () => {
  unsubBus?.()
  unsubBus = null
  // Best-effort graceful shutdown — ask the bus to ask the backend
  // to cancel every running stream so the process can exit cleanly
  // even if the user closes the window mid-stream.
  await streams.flush(1500)
})

watch(
  () => sessions.currentId,
  async (id) => {
    skills.setCurrentSession(id)
    mcps.setCurrentSession(id)
    tools.setCurrentSession(id)
    unsubBus?.()
    unsubBus = null
    if (!id) {
      messages.value = []
      return
    }
    // Subscribe first so any event arriving between the disk read
    // and the messages.value assignment isn't dropped on the floor.
    unsubBus = streams.subscribe(id, (ev) => {
      _applyEventToMessages(ev)
      scrollToBottom()
    })
    try {
      const sess = await api.getSession(id)
      const liveState = streams.getState(id)
      const liveId = liveState.assistantMessageId
      // When is the bus's live reply NOT on disk yet? Mid-stream
      // (the debounced persist deliberately excludes the in-flight
      // pending message) and in the thin window right after a
      // cancel/done before the terminal persist flushes. In both
      // cases disk ends with the user message, so a placeholder with
      // the live id + a fold recovers the exact partial content the
      // live view showed — cancelling then switching away/back must
      // land on the SAME half-consumed reply. If disk already has the
      // assistant reply (final persist landed), trust disk.
      const diskLast = sess.messages[sess.messages.length - 1]
      const hasLiveContent =
        liveState.assistantContent !== "" ||
        liveState.toolCalls.length > 0 ||
        liveState.segments.length > 0
      const needsLive =
        !!liveId &&
        diskLast?.role === "user" &&
        (liveState.streaming || hasLiveContent)
      messages.value = sess.messages.map((m) => ({ ...m, id: crypto.randomUUID() }))
      if (needsLive) {
        // The in-flight assistant message is ``pending:true`` while
        // streaming, so the bus's persist deliberately EXCLUDED it
        // from disk. The disk reload therefore has no id matching the
        // bus's ``assistantMessageId``, and without re-adding it here
        // both ``_foldLiveIntoMessages`` AND the next SSE event would
        // find nothing to update — switching away and back mid-stream
        // would silently drop the live reply. Re-add a placeholder
        // carrying the bus's id so the fold and subsequent events
        // have a target. When the stream winds down the final persist
        // writes the completed message back to disk.
        messages.value = [
          ...messages.value,
          {
            id: liveId,
            role: "assistant",
            content: "",
            pending: true,
            tool_calls: [],
            segments: [],
          } as LocalMessage,
        ]
      }
      if (sess.provider && sess.model) {
        selectedModelKey.value = `${sess.provider}::${sess.model}`
      }
      // If the bus is mid-stream for this session, the local
      // messages won't reflect the live assistant state. Patch it in.
      if (needsLive) {
        _foldLiveIntoMessages(liveState)
      }
      scrollToBottom()
    } catch {
      // ignored; user can retry
    }
  },
  { immediate: true },
)

function _applyEventToMessages(ev: import("../api/client").StreamEvent) {
  // If the user is at the bottom, stay there as new chunks come
  // in. Otherwise leave them alone so they can read old context.
  if (ev.type === "chunk") {
    const cur = messages.value[messages.value.length - 1]
    if (cur?.pending && stickToBottom.value) {
      void nextTick(() => _scrollToBottom())
    }
  }
  // Tool events: target the running assistant message
  if (ev.type === "chunk") {
    const liveId = liveAssistantId.value
    if (!liveId) return
    const m = messages.value.find((x) => x.id === liveId)
    if (!m) return
    m.content += ev.content
    // Keep the ordered timeline in sync: append to the in-progress
    // text run, or open a new one after a tool segment.
    const segs = (m.segments ??= [])
    const last = segs[segs.length - 1]
    if (last && last.kind === "text") last.content += ev.content
    else segs.push({ kind: "text", content: ev.content })
    return
  }
  if (ev.type === "reasoning") {
    const liveId = liveAssistantId.value
    if (!liveId) return
    const m = messages.value.find((x) => x.id === liveId)
    if (!m) return
    // Reasoning deltas land in a dedicated thinking block at the
    // current timeline position (before the reply text it feeds).
    const segs = (m.segments ??= [])
    const last = segs[segs.length - 1]
    if (last && last.kind === "thinking") last.content += ev.content
    else segs.push({ kind: "thinking", content: ev.content })
    return
  }
  if (ev.type === "tool_start") {
    const liveId = liveAssistantId.value
    if (!liveId) return
    const m = messages.value.find((x) => x.id === liveId)
    if (!m) return
    m.tool_calls = m.tool_calls ?? []
    const call = {
      call_id: ev.call_id,
      kind: ev.kind,
      name: ev.name,
      args: ev.args,
      status: "executing" as const,
      startedAt: Date.now(),
    }
    m.tool_calls.push(call)
    // Insert the capsule at the current timeline position instead of
    // collecting it for the bottom of the message.
    const segs = (m.segments ??= [])
    segs.push({ kind: "tool", call })
    return
  }
  if (ev.type === "tool_progress") {
    const liveId = liveAssistantId.value
    if (!liveId) return
    const idx = messages.value.findIndex((x) => x.id === liveId)
    if (idx < 0) return
    const tcs = (messages.value[idx].tool_calls ??= [])
    const tc = tcs.find((t) => t.call_id === ev.call_id)
    if (tc) tc.result = (tc.result ?? "") + ev.chunk
    const segs = messages.value[idx].segments
    const seg = segs?.find((s) => s.kind === "tool" && s.call.call_id === ev.call_id)
    if (seg && seg.kind === "tool") seg.call.result = (seg.call.result ?? "") + ev.chunk
    return
  }
  if (ev.type === "tool_end") {
    const liveId = liveAssistantId.value
    if (!liveId) return
    const idx = messages.value.findIndex((x) => x.id === liveId)
    if (idx < 0) return
    const endedAt = Date.now()
    const tcs = (messages.value[idx].tool_calls ??= [])
    const tc = tcs.find((t) => t.call_id === ev.call_id)
    if (tc) {
      tc.result = ev.result
      tc.error = ev.error ?? undefined
      tc.ok = ev.ok
      tc.cancelled = ev.cancelled ?? false
      tc.status = ev.ok ? "success" : "error"
      tc.durationMs = tc.startedAt ? endedAt - tc.startedAt : undefined
    }
    const segs = messages.value[idx].segments
    const seg = segs?.find((s) => s.kind === "tool" && s.call.call_id === ev.call_id)
    if (seg && seg.kind === "tool") {
      seg.call.result = ev.result
      seg.call.error = ev.error ?? undefined
      seg.call.ok = ev.ok
      seg.call.cancelled = ev.cancelled ?? false
      seg.call.status = ev.ok ? "success" : "error"
      seg.call.durationMs = seg.call.startedAt
        ? endedAt - seg.call.startedAt
        : undefined
    }
    return
  }
  if (ev.type === "done") {
    const liveId = liveAssistantId.value
    if (liveId) {
      const m = messages.value.find((x) => x.id === liveId)
      if (m) m.pending = false
    }
    return
  }
  if (ev.type === "cancelled") {
    const liveId = liveAssistantId.value
    if (liveId) {
      const m = messages.value.find((x) => x.id === liveId)
      if (m) {
        m.pending = false
        // Keep the partial content visible — the user stops the run
        // wherever it is. Just flag it as cancelled; the bubble shows
        // a small "cancelled" hint UNDER the content instead of
        // replacing the whole reply with the label.
        m.cancelled = true
      }
    }
    return
  }
  if (ev.type === "error") {
    const liveId = liveAssistantId.value
    if (liveId) {
      const m = messages.value.find((x) => x.id === liveId)
      if (m) {
        m.pending = false
        m.error = ev.message
      }
    }
    return
  }
}

function _foldLiveIntoMessages(state: import("../stores/sessionStreams").SessionStreamState) {
  const m = messages.value.find((x) => x.id === state.assistantMessageId)
  if (m) {
    m.content = state.assistantContent
    // Copy, don't share references: the bus keeps writing to ITS
    // state arrays as the stream continues, and the view listener
    // appends to ITS message arrays on every event. Sharing the
    // same array here would make every subsequent tool_start / chunk
    // land twice (once in the bus loop, once in the subscriber).
    m.tool_calls = state.toolCalls.map((t) => ({ ...t }))
    m.segments = state.segments.map((s) =>
      s.kind === "tool"
        ? { kind: "tool" as const, call: { ...s.call } }
        : { ...s },
    )
    m.pending = state.streaming
    m.cancelled = state.cancelled
  }
}

function onScrollNearEdge(direction: "top" | "bottom") {
  if (direction === "bottom") stickToBottom.value = true
  else stickToBottom.value = false
}

function _scrollToBottom() {
  void nextTick(() => {
    const el = scrollerEl.value?.scrollerEl
    if (el) el.scrollTop = el.scrollHeight
  })
}
function scrollToBottom() {
  stickToBottom.value = true
  _scrollToBottom()
}

function autoresize() {
  const el = composerEl.value
  if (!el || expanded.value) return
  el.style.height = "auto"
  el.style.height = `${el.scrollHeight}px`
}

watch(expanded, (v) => {
  if (!v) void nextTick(() => autoresize())
})

function composeMessagesForPersist(): ChatMessage[] {
  return messages.value
    .filter((m) => !m.pending)
    .map((m) => ({
      role: m.role,
      content: m.content,
      skills:
        m.role === "user" && m.skills && m.skills.length > 0 ? m.skills : undefined,
      mcp: m.role === "user" && m.mcp && m.mcp.length > 0 ? m.mcp : undefined,
      tools:
        m.role === "user" && m.tools && m.tools.length > 0 ? m.tools : undefined,
      // Files: persisted as metadata only. The model never sees
      // the binary; the backend splices the absolute paths into
      // the user content just before the LLM call (and the same
      // augmented content is reused across the controller's loop
      // iterations for prompt-cache stability).
      files:
        m.role === "user" && m.files && m.files.length > 0 ? m.files : undefined,
      // Persist tool_calls on assistant messages. The chat SSE
      // stream itself never sends the tool_calls array as part of
      // a message payload — the frontend accumulates them from
      // incremental ``tool_start`` / ``tool_end`` events. So the
      // persisted shape carries more than the SSE payload does,
      // exactly as the goal specifies.
      tool_calls:
        m.role === "assistant" && m.tool_calls && m.tool_calls.length > 0
          ? m.tool_calls
          : undefined,
      // Persist the cancelled flag so a reloaded session shows the
      // same partial reply + cancellation hint as the live view.
      cancelled: m.role === "assistant" && m.cancelled ? true : undefined,
      // Persist the ordered timeline too so a reload replays the
      // reply as it streamed (text and capsules interleaved), not
      // flattened to all-text-then-all-capsules. Older sessions
      // without segments fall back to content + tool_calls.
      segments:
        m.role === "assistant" && m.segments && m.segments.length > 0
          ? m.segments
          : undefined,
    }))
}

/** Convert frontend-shaped messages into the LLM-shaped array that
 *  ``/api/v1/chat`` expects. Two key differences from
 *  ``composeMessagesForPersist``:
 *
 *  1. Assistant messages keep their ``tool_calls`` field — the LLM
 *     needs to see what tools the model itself invoked in the
 *     previous turn. Without this, a cancelled / errored mid-tool
 *     turn arrives at the LLM as plain text, and the model on the
 *     next turn loses the thread ("I called X with Y" with no
 *     trace of X) — depending on the model that surfaces as
 *     hallucinated results, refusal to call tools, or worse.
 *  2. Each ``{ kind: "tool", call }`` segment becomes its own
 *     ``role: "tool"`` message carrying the tool result / error /
 *     cancellation marker, since that's the wire shape every LLM
 *     provider needs to close the loop on a tool call.
 *
 *  User-message metadata (skills / mcp / tools / files) is the
 *  per-turn attachment; the backend needs it to know which skills
 *  to re-inject and which tool/MCP schemas to expose, so it stays
 *  on the user message. The cancelled flag is purely UI metadata
 *  and intentionally omitted — the LLM can read "tool result
 *  cancelled" from the role=tool message itself. */
function buildLLMMessages(
  messages: LocalMessage[],
): ChatMessage[] {
  const out: ChatMessage[] = []
  for (const m of messages) {
    if (m.pending) continue
    if (m.role === "user") {
      const u: ChatMessage = {
        role: "user",
        content: m.content || "",
      }
      if (m.skills && m.skills.length > 0) u.skills = m.skills
      if (m.mcp && m.mcp.length > 0) u.mcp = m.mcp
      if (m.tools && m.tools.length > 0) u.tools = m.tools
      if (m.files && m.files.length > 0) u.files = m.files
      out.push(u)
    } else if (m.role === "assistant") {
      const llmToolCalls: LLMToolCall[] | undefined = m.tool_calls && m.tool_calls.length > 0
        ? m.tool_calls.map((t) => ({
            id: t.call_id,
            type: "function",
            function: {
              name: t.name,
              arguments: _safeStringifyArgs(t.args),
            },
          }))
        : undefined
      out.push({
        role: "assistant",
        content: m.content || "",
        llm_tool_calls: llmToolCalls,
      })
      // Walk the segment timeline and emit one role=tool message
      // per tool segment so the LLM sees the result / error /
      // cancellation of every call. Order matters — segments are
      // already in delivery order, so this preserves the original
      // interleaving of thinking / text / tool calls.
      if (m.segments) {
        for (const seg of m.segments) {
          if (seg.kind !== "tool") continue
          const c = seg.call
          // A cancelled tool still has a slot in the conversation:
          // emit an empty result so the LLM knows the call
          // happened and was aborted, instead of seeing an
          // un-answered assistant.tool_call (most providers will
          // either reject that or treat the next turn as a fresh
          // request, neither of which is what we want).
          out.push({
            role: "tool",
            tool_call_id: c.call_id,
            content: c.result ?? c.error ?? "",
          })
        }
      }
    }
  }
  return out
}

/** Tool args can carry non-JSON-serialisable values (Decimal,
 *  datetime, …) depending on what the LLM emitted and how the
 *  frontend parsed it. Stringify defensively so a single bad arg
 *  doesn't take down the whole request — fall back to an empty
 *  object, which is still a valid OpenAI tool_call. */
function _safeStringifyArgs(args: Record<string, unknown>): string {
  try {
    return JSON.stringify(args)
  } catch {
    return "{}"
  }
}

async function send() {
  const text = input.value.trim()
  const files = attachedFiles.value
  // Empty body OR file-only are both valid sends — the user
  // might want to send just files (the model still gets the
  // attached paths as its only context).
  if ((!text && files.length === 0) || streaming.value) return
  if (!selectedModelKey.value || !currentProviderName.value) {
    alert(t("chat.noModelSelected"))
    return
  }
  if (!sessions.currentId) {
    await sessions.create()
    if (!sessions.currentId) return
  }

  const attachedSkills = [...skills.active]
  const attachedMCPs = [...mcps.active]
  const attachedTools = [...tools.active]
  const sid = sessions.currentId
  const assistantId = crypto.randomUUID()

  const userMsg: LocalMessage = {
    id: crypto.randomUUID(),
    role: "user",
    content: text,
    skills: attachedSkills.length > 0 ? attachedSkills : undefined,
    mcp: attachedMCPs.length > 0 ? attachedMCPs : undefined,
    tools: attachedTools.length > 0 ? attachedTools : undefined,
    files: files.length > 0 ? files : undefined,
  }
  messages.value = [
    ...messages.value,
    userMsg,
    {
      id: assistantId,
      role: "assistant",
      content: "",
      pending: true,
      tool_calls: [],
      segments: [],
    } as LocalMessage,
  ]
  input.value = ""
  attachedFiles.value = []
  autoresize()
  scrollToBottom()
  expanded.value = false
  modelOpen.value = false

  const payload = {
    provider: currentProviderName.value,
    model: currentModelCode.value,
    skills: attachedSkills,
    mcp: attachedMCPs,
    tools: attachedTools,
    // LLM-shaped: assistant messages keep their tool_calls and the
    // segment timeline is expanded into role=tool result messages.
    // Without this, a turn that got cancelled mid-tool arrives at
    // the model as plain text and the next call loses context.
    messages: buildLLMMessages(messages.value),
  }

  // Fire and forget — the bus owns the stream from here. The base
  // message list is composed NOW, while ``messages.value`` is still
  // this session's array (it holds the just-pushed user message and
  // the session's full history). The bus stores this baseline
  // per-session and never reads the shared ``messages.value`` again,
  // so switching sessions mid-stream can't cross-contaminate the
  // persisted histories. Its own debounced persist + terminal persist
  // append the live assistant reply; the immediate persist it does on
  // start guarantees this instruction lands on disk before any chunk
  // arrives (a quick switch-away can't orphan it).
  void streams.start(
    sid,
    payload,
    assistantId,
    composeMessagesForPersist(),
  )

  // Auto-title: on the first user message of a session whose title is
  // still the "New chat" placeholder, ask the backend to summarise
  // the user's intent into a Chinese title ≤10 chars and update the
  // sidebar when it arrives. Runs in parallel with the chat stream —
  // we don't await it, and a slow / failed LLM call never blocks the
  // main conversation (the backend falls back to truncating the user
  // message, or no-ops if the user already renamed the session).
  //
  // Title handling on the first user message of a session. The
  // sidebar must show a title AT the moment the user hits send —
  // NOT whenever the LLM title call happens to finish. The title
  // call is a tiny completion that can queue for ~a minute behind
  // active chat streams (provider-side concurrency limit), which
  // made the rename feel randomly late once multiple sessions run
  // in parallel. So we set the title optimistically from the user's
  // own words right now (deterministic, instant), then let the LLM
  // refine it in the background; the backend skips refinement when
  // it sees a non-placeholder title, and the frontend gate below
  // ensures this block runs at most once per session.
  const titleBeforeSend =
    sessions.items.find((s) => s.id === sid)?.title ?? ""
  if (titleBeforeSend === "New chat" && text) {
    const optimistic = text.trim().slice(0, 60) || t("sessions.new")
    sessions.applyAutoTitle(sid, optimistic)
    void _requestAutoTitle(
      sid,
      text,
      currentProviderName.value,
      currentModelCode.value,
    )
  }
}

/** User clicked the red square while a stream was active. Ask the
 *  bus to abort the SSE connection and tell the backend to stop the
 *  LLM mid-flight. The bus's terminal ``_persist`` then writes the
 *  partial assistant content into the session store before the loop
 *  unwinds — see ``sessionStreams.start``'s ``finally``. */
async function stop() {
  if (!streaming.value) return
  const sid = sessions.currentId
  if (!sid) return
  // Fire and forget — the cancel sets ``state.cancelled = true`` and
  // the bus emits a ``cancelled`` event in response. The button
  // reappears automatically because the ``streaming`` computed
  // reacts to the same state.
  void streams.cancel(sid)
}

/** Fire-and-forget auto-title request. Updates the sidebar when
 *  the backend returns; logs but otherwise swallows errors (the
 *  main chat stream should never be impacted by a title-gen
 *  failure). */
async function _requestAutoTitle(
  sid: string,
  userMessage: string,
  provider: string,
  model: string,
) {
  try {
    const r = await api.autoTitleSession(sid, {
      user_message: userMessage,
      provider,
      model,
    })
    if (r.source !== "kept" && r.title) {
      sessions.applyAutoTitle(sid, r.title)
    }
  } catch (e) {
    // Surface in dev console only; the user still sees a usable
    // session in the sidebar (the bus debounced-persist path
    // truncates the first user message to 60 chars as a
    // safety-net fallback).
    console.error("[chat] auto-title failed:", e)
  }
}

function toggleExpanded() {
  expanded.value = !expanded.value
  if (expanded.value) void nextTick(() => composerEl.value?.focus())
}

function toggleModelPicker() {
  modelOpen.value = !modelOpen.value
  if (modelOpen.value) void nextTick(() => composerEl.value?.focus())
}

function selectModel(providerName: string, modelCode: string) {
  selectedModelKey.value = `${providerName}::${modelCode}`
  modelOpen.value = false
  void nextTick(() => composerEl.value?.focus())
}

async function newSession() {
  await sessions.create()
}

/** Resolve a File to its absolute path on disk.
 *
 * Electron 32+ removed the synchronous ``File.path`` attribute for
 * security (it leaked OS paths into the renderer without an
 * explicit user gesture). The replacement is the preload-bridged
 * ``webUtils.getPathForFile(file)`` — we never expose the raw
 * ``webUtils`` object to the page, we only expose a tiny
 * ``getPathForFile(file)`` shim that returns "" on any failure.
 *
 * In a non-Electron browser (vite dev, no preload) the shim is
 * missing — we fall back to the legacy ``File.path`` property
 * for that dev path, which still works in Chromium for now.
 * Production builds always go through the preload bridge.
 */
function resolveAbsolutePath(f: File): string {
  const w = window as unknown as { mhc?: { getPathForFile?: (f: File) => string } }
  if (w.mhc && typeof w.mhc.getPathForFile === "function") {
    return w.mhc.getPathForFile(f)
  }
  // Dev fallback (vite-only; no preload in the page).
  return (f as File & { path?: string }).path ?? ""
}

/** Convert a FileList (from <input type="file"> or drag-drop) into
 *  the ChatFileAttachment shape, deduping by absolute path and
 *  capping at MAX_FILES.
 *
 *  In Electron, the absolute path comes from
 *  ``webUtils.getPathForFile(file)`` (exposed via preload). In a
 *  non-Electron browser, paths are empty — those entries are kept
 *  (the user still sees them in the chip row) but the backend
 *  renders a name-only line for the model so it knows the
 *  attachment exists. */
function pickAttachments(list: FileList | File[]): Array<{
  name: string
  path: string
  size: number
  type: string
}> {
  const existing = new Set(attachedFiles.value.map((f) => f.path))
  const out: Array<{ name: string; path: string; size: number; type: string }> = []
  for (const f of Array.from(list)) {
    const path = resolveAbsolutePath(f)
    if (path && existing.has(path)) continue
    out.push({
      name: f.name,
      path,
      size: f.size ?? 0,
      type: f.type ?? "",
    })
    if (path) existing.add(path)
    if (attachedFiles.value.length + out.length >= MAX_FILES) break
  }
  return out
}

function addFiles(list: FileList | File[] | null | undefined) {
  if (!list) return
  const picks = pickAttachments(list)
  if (picks.length === 0) return
  // Cap silently — the chip row already reflects the limit, and a
  // modal here would interrupt the user's flow mid-drag.
  const room = MAX_FILES - attachedFiles.value.length
  if (room <= 0) return
  attachedFiles.value = [...attachedFiles.value, ...picks.slice(0, room)]
}

function removeFile(idx: number) {
  attachedFiles.value = attachedFiles.value.filter((_, i) => i !== idx)
}

function clearAttachedFiles() {
  attachedFiles.value = []
}

function fileInputEl(): HTMLInputElement | null {
  // The hidden <input type=file> lives in the composer — we
  // grab it by id and click programmatically when the user
  // taps the paperclip button.
  return document.getElementById("chat-file-input") as HTMLInputElement | null
}

function openFilePicker() {
  fileInputEl()?.click()
}

function onFilePicked(ev: Event) {
  const inputEl = ev.target as HTMLInputElement
  addFiles(inputEl.files)
  // Reset so the user can re-pick the SAME file later (change
  // events on identical selections don't fire otherwise).
  inputEl.value = ""
}

function onComposerDragOver(ev: DragEvent) {
  // Required so the drop event actually fires. We don't show a
  // custom drop overlay — the composer highlight on hover is
  // enough signal. preventDefault stops the browser from opening
  // the file in a new tab.
  if (!ev.dataTransfer) return
  if (!Array.from(ev.dataTransfer.types).includes("Files")) return
  ev.preventDefault()
}

function onComposerDrop(ev: DragEvent) {
  if (!ev.dataTransfer) return
  if (ev.dataTransfer.files.length === 0) return
  ev.preventDefault()
  addFiles(ev.dataTransfer.files)
}

function skillName(slug: string): string {
  return skills.items.find((s) => s.slug === slug)?.name ?? slug
}
function mcpName(slug: string): string {
  return mcps.items.find((s) => s.slug === slug)?.name ?? slug
}
function toolName(slug: string): string {
  return tools.items.find((s) => s.slug === slug)?.name ?? slug
}
function toolSlug(name: string): string {
  // MCP names are "<slug>::<tool>", Tool names are just "<slug>".
  return name.split("::")[0] ?? ""
}
function toolShortName(name: string): string {
  return name.includes("::") ? name.split("::")[1] : name
}

/** Only the tail text run of a pending reply shows the streaming
 *  cursor; completed runs render as final markdown. */
function isStreamingSegment(
  m: LocalMessage,
  si: number,
): boolean {
  if (!m.segments) return false
  const lastIndex = m.segments.length - 1
  return si === lastIndex && m.segments[si].kind === "text"
}

/** Count tool segments in a message. Used to decide whether the
 *  timeline should auto-collapse into a compact summary — runs
 *  with many tools otherwise dominate the conversation column. */
function toolSegmentCount(m: LocalMessage): number {
  if (!m.segments) return 0
  return m.segments.filter((s) => s.kind === "tool").length
}

/** Distinct tool names (shortName) in delivery order. Used by the
 *  compact summary to give the user a glanceable list. */
function toolSummaryNames(m: LocalMessage): string[] {
  if (!m.segments) return []
  const seen = new Set<string>()
  const out: string[] = []
  for (const s of m.segments) {
    if (s.kind !== "tool") continue
    const short = toolShortName(s.call.name)
    if (!seen.has(short)) {
      seen.add(short)
      out.push(short)
    }
  }
  return out
}

/** Group consecutive tool segments into runs so the timeline can
 *  lay each run on a single horizontal row (with wrap). Text and
 *  thinking segments stay as their own items so they keep the
 *  model’s natural rhythm. */
type TimelineGroup =
  | { kind: "tool"; seg: Extract<NonNullable<LocalMessage["segments"]>[number], { kind: "tool" }> }
  | { kind: "thinking"; seg: Extract<NonNullable<LocalMessage["segments"]>[number], { kind: "thinking" }> }
  | { kind: "text"; seg: Extract<NonNullable<LocalMessage["segments"]>[number], { kind: "text" }> }
  | { kind: "tool-run"; segs: Extract<NonNullable<LocalMessage["segments"]>[number], { kind: "tool" }>[] }

function groupTimelineSegments(
  segments: NonNullable<LocalMessage["segments"]>,
): TimelineGroup[] {
  const out: TimelineGroup[] = []
  let i = 0
  while (i < segments.length) {
    const seg = segments[i]
    if (seg.kind === "tool") {
      const segs = [seg]
      i++
      while (i < segments.length && segments[i].kind === "tool") {
        segs.push(segments[i] as typeof segs[number])
        i++
      }
      out.push({ kind: "tool-run", segs })
    } else if (seg.kind === "thinking") {
      out.push({ kind: "thinking", seg })
      i++
    } else {
      out.push({ kind: "text", seg })
      i++
    }
  }
  return out
}
</script>

<template>
  <section class="chat">
    <p v-if="messages.length === 0" class="empty">
      <span class="empty-title">{{ t("chat.emptyTitle") }}</span>
      <span class="empty-sub">{{ t("chat.emptySub") }}</span>
    </p>
    <VirtualMessageList
      v-else
      ref="scrollerEl"
      :messages="messages"
      :on-scroll-near-edge="onScrollNearEdge"
      :estimated-row-height="80"
    >
      <template #default="{ item }">
        <div
          class="msg"
          :class="(item as unknown as LocalMessage).role"
          :data-vmsg="(item as unknown as LocalMessage).id"
        >
          <div class="content">
            <span v-if="(item as unknown as LocalMessage).error" class="error">{{ (item as unknown as LocalMessage).error }}</span>
            <template
              v-else-if="
                (item as unknown as LocalMessage).role === 'assistant' &&
                (item as unknown as LocalMessage).segments &&
                (item as unknown as LocalMessage).segments!.length > 0
              "
            >
              <!-- Ordered timeline: text runs and tool capsules in
                   the exact sequence the model produced them.
                   Thinking, prose and tool calls interleave instead
                   of all capsules being dumped under the text. -->
              <div
                v-if="
                  toolSegmentCount(item as unknown as LocalMessage) > 5 &&
                  !(toolChainOpen[(item as unknown as LocalMessage).id] ?? false)
                "
                class="tool-summary"
              >
                <Icon name="package" :width="13" :height="13" />
                <span class="tool-summary-text">
                  Ran {{ toolSegmentCount(item as unknown as LocalMessage) }}
                  tools · {{ toolSummaryNames(item as unknown as LocalMessage).join(', ') }}
                </span>
                <button
                  class="tool-summary-btn"
                  @click="toolChainOpen[(item as unknown as LocalMessage).id] = true"
                >
                  <Icon name="chevron-down" :width="12" :height="12" />
                  <span>Show timeline</span>
                </button>
              </div>
              <div v-else class="timeline" role="list">
                <template
                  v-for="(grp, gi) in groupTimelineSegments((item as unknown as LocalMessage).segments!)"
                  :key="gi"
                >
                  <!-- A row of one or more consecutive tool calls.
                       When they don't fit, they wrap to the next
                       line — the timeline keeps tools as visually
                       compact runs instead of one-per-row. -->
                  <div
                    v-if="grp.kind === 'tool-run'"
                    class="tl-tool-row"
                    role="list"
                  >
                    <ToolCallCapsule
                      v-for="(seg, ti) in grp.segs"
                      :key="ti"
                      class="tl-tool"
                      role="listitem"
                      :name="seg.call.name"
                      :kind="seg.call.kind"
                      :status="seg.call.status"
                      :args="seg.call.args"
                      :result="seg.call.result"
                      :error="seg.call.error"
                      :slug="toolSlug(seg.call.name)"
                      :short-name="toolShortName(seg.call.name)"
                      :started-at="seg.call.startedAt"
                      :duration-ms="seg.call.durationMs"
                    />
                  </div>
                  <MarkdownView
                    v-else-if="grp.kind === 'text'"
                    class="tl-text"
                    :source="grp.seg.content"
                    :streaming="
                      !!(item as unknown as LocalMessage).pending &&
                      isStreamingSegment(item as unknown as LocalMessage, (item as unknown as LocalMessage).segments!.indexOf(grp.seg))
                    "
                  />
                  <!-- Thinking block: the model's reasoning, dimmed
                       and set apart from the visible reply. -->
                  <ThinkingBlock
                    v-else-if="grp.kind === 'thinking'"
                    class="tl-tool"
                    :content="grp.seg.content"
                    :streaming="
                      !!(item as unknown as LocalMessage).pending
                    "
                  />
                </template>
              </div>
            </template>
            <MarkdownView
              v-else-if="(item as unknown as LocalMessage).role === 'assistant'"
              :source="(item as unknown as LocalMessage).content"
              :streaming="!!(item as unknown as LocalMessage).pending"
            />
            <template v-else>
              <span style="white-space: pre-wrap">{{ (item as unknown as LocalMessage).content }}</span>
            </template>

            <div
              v-if="
                !(
                  (item as unknown as LocalMessage).segments &&
                  (item as unknown as LocalMessage).segments!.length > 0
                ) &&
                (item as unknown as LocalMessage).tool_calls &&
                (item as unknown as LocalMessage).tool_calls!.length > 0
              "
              class="tool-capsules"
              role="list"
              :aria-label="t('chat.toolCalls')"
            >
              <ToolCallCapsule
                v-for="tc in (item as unknown as LocalMessage).tool_calls"
                :key="tc.call_id"
                :name="tc.name"
                :kind="tc.kind"
                :status="tc.status"
                :args="tc.args"
                :result="tc.result"
                :error="tc.error"
                :slug="toolSlug(tc.name)"
                :short-name="toolShortName(tc.name)"
                :started-at="tc.startedAt"
                :duration-ms="tc.durationMs"
              />
            </div>

            <div
              v-if="(item as unknown as LocalMessage).role === 'user' && (item as unknown as LocalMessage).skills && (item as unknown as LocalMessage).skills!.length > 0"
              class="msg-skills"
              :title="t('chat.attachedSkillsTitle')"
            >
              <span class="msg-skills-icon" aria-hidden="true">⊕</span>
              <span class="msg-skills-label">{{ t('chat.attachedSkills', { count: (item as unknown as LocalMessage).skills!.length }) }}</span>
              <span class="msg-skills-list">
                <span v-for="slug in (item as unknown as LocalMessage).skills" :key="slug" class="msg-skills-pill">
                  {{ skillName(slug) }}
                </span>
              </span>
            </div>
            <div
              v-if="(item as unknown as LocalMessage).role === 'user' && (item as unknown as LocalMessage).mcp && (item as unknown as LocalMessage).mcp!.length > 0"
              class="msg-skills"
              :title="t('chat.attachedMCPTitle')"
            >
              <span class="msg-skills-icon" aria-hidden="true">⚙</span>
              <span class="msg-skills-label">{{ t('chat.attachedMCP', { count: (item as unknown as LocalMessage).mcp!.length }) }}</span>
              <span class="msg-skills-list">
                <span v-for="slug in (item as unknown as LocalMessage).mcp" :key="slug" class="msg-skills-pill">
                  {{ mcpName(slug) }}
                </span>
              </span>
            </div>
            <div
              v-if="(item as unknown as LocalMessage).role === 'user' && (item as unknown as LocalMessage).tools && (item as unknown as LocalMessage).tools!.length > 0"
              class="msg-skills msg-tools"
              :title="t('chat.attachedToolsTitle')"
            >
              <span class="msg-skills-icon" aria-hidden="true">🛠</span>
              <span class="msg-skills-label">{{ t('chat.attachedTools', { count: (item as unknown as LocalMessage).tools!.length }) }}</span>
              <span class="msg-skills-list">
                <span v-for="slug in (item as unknown as LocalMessage).tools" :key="slug" class="msg-skills-pill">
                  {{ toolName(slug) }}
                </span>
              </span>
            </div>

            <!-- Attached files. Same visual position as the
                 skill/MCP/tool chip rows so the bubble's footer
                 is consistent. Files get a slightly larger
                 capsule (user-facing requirement: "files are a
                 common type, so a slightly larger pill is
                 fine"). On reload the chips rebuild from the
                 persisted ``files`` metadata so the rebuilt UI
                 matches what the user saw when sending. -->
            <div
              v-if="(item as unknown as LocalMessage).role === 'user' && (item as unknown as LocalMessage).files && (item as unknown as LocalMessage).files!.length > 0"
              class="msg-skills msg-files"
              :title="t('chat.attachedFilesTitle')"
            >
              <span class="msg-skills-icon" aria-hidden="true">📎</span>
              <span class="msg-skills-label">{{ t('chat.attachedFiles', { count: (item as unknown as LocalMessage).files!.length }) }}</span>
              <span class="msg-files-list">
                <span
                  v-for="(f, fi) in (item as unknown as LocalMessage).files"
                  :key="(f.path || f.name) + ':' + fi"
                  class="msg-files-pill"
                  :title="f.path || t('chat.fileNoPath')"
                >
                  <span class="msg-files-pill-name">{{ f.name }}</span>
                </span>
              </span>
            </div>

            <!-- Cancelled hint. A stopped run keeps everything the
                 user already consumed; this small footer line marks
                 the point where the reply was cut off instead of
                 replacing the whole bubble with the label. Reloads
                 reproduce it from the persisted ``cancelled`` flag. -->
            <div
              v-if="(item as unknown as LocalMessage).cancelled"
              class="cancel-hint"
              :title="t('chat.cancelledTitle')"
            >
              <span class="cancel-hint-icon" aria-hidden="true">■</span>
              <span>{{ t("chat.cancelled") }}</span>
            </div>
          </div>
        </div>
      </template>
    </VirtualMessageList>

    <!-- Persistent loading indicator while the agent is still
         streaming. Earlier the only signal was a tiny ellipsis inside
         the assistant bubble that vanished on the first token, so a
         mid-stream stall looked like "generation finished".
         This row stays at the bottom of the conversation until the
         stream ends (or errors). -->
    <div
      v-if="streaming && !streamingError"
      class="streaming-bar"
      :class="{ expanded }"
      role="status"
      aria-live="polite"
    >
      <div class="streaming-bar-dots" aria-hidden="true">
        <span /><span /><span />
      </div>
      <span class="streaming-bar-label">{{ t('chat.streaming') }}</span>
    </div>

    <div v-if="expanded" class="backdrop" @click="expanded = false" />

    <div
      v-if="skills.active.size > 0 || mcps.active.size > 0 || tools.active.size > 0"
      class="active-bar"
      :class="{ expanded }"
    >
      <div class="active-bar-inner">
        <span class="active-label">
          {{
            [
              skills.active.size > 0
                ? t('skills.activeChip', { count: skills.active.size })
                : '',
              mcps.active.size > 0
                ? t('mcp.activeChip', { count: mcps.active.size })
                : '',
              tools.active.size > 0
                ? t('tools.activeChip', { count: tools.active.size })
                : '',
            ]
              .filter(Boolean)
              .join(' · ')
          }}
        </span>
        <div class="active-chips">
          <span
            v-for="slug in [...skills.active]"
            :key="`skill:${slug}`"
            class="active-chip"
          >
            {{ skills.items.find((s) => s.slug === slug)?.name ?? slug }}
            <button
              class="chip-x"
              :title="t('common.delete')"
              @click="skills.toggleActive(slug)"
            >×</button>
          </span>
          <span
            v-for="slug in [...mcps.active]"
            :key="`mcp:${slug}`"
            class="active-chip mcp-chip"
          >
            {{ mcps.items.find((s) => s.slug === slug)?.name ?? slug }}
            <button
              class="chip-x"
              :title="t('common.delete')"
              @click="mcps.toggleActive(slug)"
            >×</button>
          </span>
          <span
            v-for="slug in [...tools.active]"
            :key="`tool:${slug}`"
            class="active-chip tool-chip"
          >
            {{ tools.items.find((t) => t.slug === slug)?.name ?? slug }}
            <button
              class="chip-x"
              :title="t('common.delete')"
              @click="tools.toggleActive(slug)"
            >×</button>
          </span>
        </div>
      </div>
    </div>

    <div class="composer-wrap" :class="{ expanded }">
      <div
        class="composer"
        @dragover="onComposerDragOver"
        @drop="onComposerDrop"
      >
        <!-- Pending file attachments live just above the textarea.
             They're shown until the user clears them or sends.
             Each chip has a × to remove individually; clearing all
             happens implicitly on send. -->
        <div
          v-if="attachedFiles.length > 0"
          class="composer-files"
          :title="t('chat.attachedFilesTitle')"
        >
          <span class="composer-files-label">
            {{ t("chat.attachedFiles", { count: attachedFiles.length }) }}
          </span>
          <span class="composer-files-list">
            <span
              v-for="(f, i) in attachedFiles"
              :key="f.path + ':' + i"
              class="composer-files-pill"
              :title="f.path || t('chat.fileNoPath')"
            >
              <span class="composer-files-pill-name">{{ f.name }}</span>
              <button
                type="button"
                class="composer-files-pill-x"
                :title="t('common.delete')"
                @click="removeFile(i)"
              >×</button>
            </span>
          </span>
        </div>

        <textarea
          ref="composerEl"
          v-model="input"
          rows="1"
          class="composer-input"
          :placeholder="
            expanded ? t('chat.placeholderExpanded') : t('chat.placeholder')
          "
          @input="autoresize"
          @keydown.enter.exact.prevent="send"
          @keydown.escape="expanded = false"
          @keydown.escape.stop="modelOpen = false"
        />

        <!-- Hidden file picker. The paperclip button below
             triggers it. ``accept`` is omitted so the user can
             pick anything; the model decides how to read it
             through its tools. -->
        <input
          id="chat-file-input"
          type="file"
          multiple
          class="composer-files-hidden"
          @change="onFilePicked"
        />

        <div class="actions">
          <div class="actions-left">
            <button
              class="ax ax-icon"
              type="button"
              :title="t('sessions.new')"
              :disabled="streaming"
              @click="newSession"
            >
              <Icon name="plus" />
            </button>

            <!-- Paperclip button: opens the hidden file picker.
                 Disabled when 5 files are already attached so the
                 user gets a tactile signal that the cap is hit.
                 Drag-and-drop still works even when the picker
                 is disabled (the cap is enforced inside the
                 drop handler). -->
            <button
              class="ax ax-icon"
              type="button"
              :title="
                attachedFiles.length >= MAX_FILES
                  ? t('chat.attachedFilesMax')
                  : t('chat.attachFiles')
              "
              :disabled="streaming || attachedFiles.length >= MAX_FILES"
              @click="openFilePicker"
            >
              <Icon name="paperclip" />
            </button>

            <div class="model-picker" ref="modelPickerEl">
              <button
                class="ax ax-pill"
                type="button"
                :disabled="enabledProviders.length === 0"
                @click="toggleModelPicker"
                :title="currentModelLabel || t('chat.pickModel')"
              >
                <span class="ax-pill-label">{{
                  currentModelLabel || t("chat.pickModel")
                }}</span>
                <Icon :name="modelOpen ? 'chevron-up' : 'chevron-down'" />
              </button>

              <Transition name="picker">
                <div v-if="modelOpen" class="picker-pop" @click.stop>
                  <div
                    v-if="enabledProviders.length === 0"
                    class="picker-empty"
                  >
                    {{ t("chat.noProvidersHint") }}
                  </div>
                  <div
                    v-for="p in enabledProviders"
                    :key="p.name"
                    class="picker-group"
                  >
                    <div class="picker-group-label">{{ p.name }}</div>
                    <button
                      v-for="m in p.models"
                      :key="p.name + '::' + m.code"
                      class="picker-item"
                      :class="{
                        selected:
                          selectedModelKey === p.name + '::' + m.code,
                      }"
                      type="button"
                      @click="selectModel(p.name, m.code)"
                    >
                      <span class="picker-item-label">{{
                        m.display_name || m.code
                      }}</span>
                      <span class="picker-item-ctx" v-if="m.max_context">
                        {{ Math.round(m.max_context / 1000) }}K
                      </span>
                      <Icon
                        v-if="
                          selectedModelKey === p.name + '::' + m.code
                        "
                        name="check"
                        class="picker-check"
                      />
                    </button>
                    <button
                      v-if="p.models.length === 0"
                      class="picker-item"
                      :class="{
                        selected:
                          selectedModelKey ===
                          p.name + '::' + (p.default_model || ''),
                      }"
                      type="button"
                      @click="selectModel(p.name, p.default_model || '')"
                    >
                      <span class="picker-item-label">{{
                        p.default_model || t("chat.pickModel")
                      }}</span>
                      <Icon
                        v-if="
                          selectedModelKey ===
                          p.name + '::' + (p.default_model || '')
                        "
                        name="check"
                        class="picker-check"
                      />
                    </button>
                  </div>
                </div>
              </Transition>
            </div>

            <button
              class="ax ax-icon"
              type="button"
              :title="
                expanded ? t('chat.exitFullscreen') : t('chat.fullscreen')
              "
              @click="toggleExpanded"
            >
              <Icon :name="expanded ? 'minimize' : 'maximize'" />
            </button>

            <!-- Context usage: prompt + completion vs model's max.
                 Hidden until the first ``done`` event delivers usage.
                 The bar is segmented so the user can see how much of
                 the budget is system + history vs the assistant's
                 response. -->
            <div
              v-if="contextUsage"
              class="ctx-meter"
              :title="t('chat.contextTitle', {
                prompt: contextUsage.prompt,
                completion: contextUsage.completion,
                max: modelMaxContext,
              })"
            >
              <svg viewBox="0 0 36 36" class="ctx-ring" aria-hidden="true">
                <circle
                  cx="18" cy="18" r="15.9155"
                  class="ctx-ring-track"
                />
                <circle
                  cx="18" cy="18" r="15.9155"
                  class="ctx-ring-fill"
                  :class="ctxRingClass"
                  :stroke-dasharray="ctxRingDasharray"
                  stroke-dashoffset="0"
                  transform="rotate(-90 18 18)"
                />
              </svg>
              <span class="ctx-meter-label" :class="ctxRingClass">
                {{ Math.round(contextRatio * 100) }}%
              </span>
            </div>
          </div>

          <div class="actions-right">
            <!--
              Send / Stop button. While ``streaming`` is true we morph
              into a red square stop button (same shape as the recordings
              UI uses) that calls ``streams.cancel(sid)``. The cancel
              path triggers ``cancelled`` from the backend and the
              bus's terminal ``_persist`` fires — partial assistant
              content lands on disk before the SSE loop exits, so
              closing the window mid-stream doesn't lose anything.
            -->
            <button
              v-if="streaming"
              class="ax ax-stop"
              type="button"
              :title="t('chat.stop')"
              :aria-label="t('chat.stop')"
              @click="stop"
            >
              <span class="stop-square" aria-hidden="true"></span>
            </button>
            <button
              v-else
              class="ax ax-send"
              type="button"
              :disabled="!input.trim() && attachedFiles.length === 0"
              :title="t('chat.send')"
              @click="send"
            >
              <Icon name="send" />
            </button>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.chat {
  display: grid;
  grid-template-rows: 1fr auto;
  height: 100%;
  background: var(--bg);
  overflow: hidden;
}

.empty {
  text-align: center;
  color: var(--text-faint);
  margin-top: 20vh;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.vmsg-scroller {
  padding: 32px 0 24px;
}
.vmsg-inner {
  display: flex;
  flex-direction: column;
  gap: 20px;
}
.empty-title {
  font-size: 18px;
  color: var(--text-mid);
}
.empty-sub {
  font-size: 13px;
}
.msg {
  max-width: clamp(720px, 78vw, 960px);
  width: 100%;
  margin: 0 auto;
  padding: 0 32px;
}

/* User messages render as right-aligned bubbles; assistant replies
   flow full-width like prose. No USER/ASSISTANT labels above. */
.msg.user .content {
  margin-left: auto;
  max-width: min(78%, 640px);
  background: var(--bg-subtle);
  border-radius: 14px;
  border-top-right-radius: 4px;
  padding: 10px 14px;
  border: 1px solid var(--border);
  font-size: var(--app-font-size, 14px);
  line-height: 1.6;
}
.msg.assistant .content {
  font-size: var(--app-font-size, 14px);
  line-height: 1.6;
  padding: 6px 0;
}

/* Tool-call capsule row (legacy layout, for sessions persisted
   before the ordered timeline existed). Sits below the assistant
   text and lays each call left-to-right. */
.tool-capsules {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

/* Ordered timeline of an assistant reply: text runs and tool
   capsules interleaved in delivery order. Text keeps flowing
   normally; capsules hang in the row where they happened. */
.timeline {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.timeline :deep(.tl-text) {
  margin: 0;
}
.timeline .tl-tool {
  align-self: flex-start;
}

/* A run of consecutive tool calls. Lay them out horizontally;
   wrap to the next line when the row would overflow. Same gap
   rhythm as the timeline so multiple rows still feel like one
   response. */
.timeline .tl-tool-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}

/* Compact summary row shown in place of a long tool chain. Hides
   >5 capsules behind one click, so the conversation column doesn't
   get dominated by an enormous run. */
.tool-summary {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--bg-subtle);
  color: var(--text-mid);
  font-size: var(--app-font-size, 12px);
  align-self: flex-start;
}
.tool-summary-text {
  color: var(--text);
  font-variant-numeric: tabular-nums;
}
.tool-summary-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 6px;
  margin-left: 2px;
  border: 0;
  background: transparent;
  color: var(--accent);
  font: inherit;
  cursor: pointer;
}
.tool-summary-btn:hover {
  text-decoration: underline;
}

.msg-skills {
  margin-top: 8px;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  font-size: var(--app-font-size, 12px);
  color: var(--text-mid);
}
.msg-skills-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  border-radius: 4px;
  background: var(--accent-soft);
  color: var(--accent);
  font-weight: 700;
  font-size: 11px;
  line-height: 1;
}
.msg-skills-label {
  font-weight: 500;
}
.msg-skills-list {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.msg-skills-pill {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 1px 8px;
  font-size: 10.5px;
  color: var(--text-mute);
}
.msg-tools .msg-skills-icon {
  background: rgba(168, 107, 255, 0.14);
  color: #a86bff;
}
.msg-tools .msg-skills-pill {
  background: rgba(168, 107, 255, 0.08);
  border-color: rgba(168, 107, 255, 0.32);
  color: #a86bff;
}

/* ── Attached files (chip row under user bubbles) ─────────────── */
/* Files are the most common attachment type, so the pill is
   slightly larger than skill/MCP/tool pills — taller, more
   padding, bigger font. The icon uses the same accent-soft
   bucket as skills (no purple). Multiple pills lay out in a
   row that wraps to the next line when the bubble is narrow. */
.msg-files .msg-skills-icon {
  background: var(--accent-soft);
  color: var(--accent);
}
.msg-files-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  max-width: 100%;
}
.msg-files-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 3px 11px;
  font-size: 12px;
  color: var(--text);
  max-width: 100%;
  /* Filenames can be long; ellipsize instead of wrapping the
     pill text so the row stays tidy on overflow. */
  min-width: 0;
}
.msg-files-pill-name {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 22ch;
}
.error {
  color: var(--danger);
  font-size: 13px;
}

/* Cancelled hint: a quiet footer line under the partial reply.
   The content the user consumed stays visible; this just marks
   where the run was cut off. */
.cancel-hint {
  margin-top: 10px;
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-mute);
}
.cancel-hint-icon {
  color: var(--danger);
  font-size: 9px;
  line-height: 1;
}

.composer-wrap {
  padding: 14px 32px 20px;
  background: var(--fade);
}
.composer {
  max-width: clamp(720px, 78vw, 960px);
  margin: 0 auto;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 18px;
  box-shadow: var(--shadow);
  transition: border-color 120ms ease, box-shadow 120ms ease;
  display: flex;
  flex-direction: column;
}
.composer:focus-within {
  border-color: var(--accent);
  box-shadow: var(--shadow-hover);
}

/* ── Pending files chip row (above the textarea) ─────────────── */
/* One row per composer: label + a flex-wrap row of pills.
   Same horizontal-wrap behaviour as the bubble-footer chip
   row, just in the input area. Pills here carry an × so the
   user can drop individual files before sending. */
.composer-files {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  padding: 10px 20px 0;
  border-bottom: 1px dashed var(--border);
  margin-bottom: 2px;
}
.composer-files-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-mid);
  letter-spacing: 0.02em;
}
.composer-files-list {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  min-width: 0;
}
.composer-files-pill {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  background: var(--accent-soft);
  border: 1px solid color-mix(in srgb, var(--accent) 30%, transparent);
  border-radius: 999px;
  padding: 2px 4px 2px 10px;
  font-size: 11.5px;
  color: var(--text);
  max-width: 100%;
  min-width: 0;
}
.composer-files-pill-name {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 22ch;
}
.composer-files-pill-x {
  border: 0;
  background: transparent;
  color: var(--text-faint);
  cursor: pointer;
  font-size: 13px;
  line-height: 1;
  padding: 0 6px;
  border-radius: 999px;
  transition: background 120ms ease, color 120ms ease;
}
.composer-files-pill-x:hover {
  background: color-mix(in srgb, var(--accent) 25%, transparent);
  color: var(--text);
}
/* Hidden file picker — zero-size, off-screen but reachable by
   the paperclip button's click(). */
.composer-files-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  opacity: 0;
  pointer-events: none;
  clip: rect(0 0 0 0);
}

.composer-input {
  flex: 0 0 auto;
  border: 0;
  outline: 0;
  resize: none;
  font: inherit;
  font-size: var(--app-font-size, 14px);
  line-height: 1.6;
  padding: 16px 20px 10px;
  background: transparent;
  color: var(--text);
  width: 100%;
  max-height: calc(1.6em * 4 + 24px);
  overflow-y: auto;
}
.composer-input::placeholder {
  color: var(--text-faint);
}

.actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 4px 8px 8px;
}
.actions-left {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  flex: 1;
  flex-wrap: wrap;
}
.actions-right {
  flex-shrink: 0;
}

/* Context usage meter — small circular badge on the left of the
 * actions row. Threshold colors: green < 40%, yellow 40-70%, red ≥ 70%.
 * Stroke-dasharray drives the ring fill so the user can see at a
 * glance how close the conversation is to the model's max context. */
.ctx-meter {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  position: relative;
  margin-left: 4px;
  width: 32px;
  height: 32px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--bg);
  cursor: default;
  transition: border-color 120ms ease, color 120ms ease;
}
.ctx-meter:hover {
  border-color: var(--accent);
}
.ctx-ring {
  width: 22px;
  height: 22px;
}
.ctx-ring-track {
  fill: none;
  stroke: var(--bg-hover);
  stroke-width: 3;
}
.ctx-ring-fill {
  fill: none;
  stroke-width: 3;
  stroke-linecap: round;
  transition: stroke-dasharray 200ms ease, stroke 200ms ease;
}
.ctx-ring-fill.ctx-warn-low { stroke: #34a853; }
.ctx-ring-fill.ctx-warn-mid { stroke: #f5a623; }
.ctx-ring-fill.ctx-warn-high { stroke: #e34c4c; }

.ctx-meter-label {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 9px;
  font-variant-numeric: tabular-nums;
  font-weight: 600;
  color: var(--text-mid);
  line-height: 1;
}
.ctx-meter-label.ctx-warn-low { color: #34a853; }
.ctx-meter-label.ctx-warn-mid { color: #f5a623; }
.ctx-meter-label.ctx-warn-high { color: #e34c4c; }

/* ── Active skills chip bar ──────────────────────────────────────────────── */
.streaming-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 32px 12px;
  margin: 0 auto;
  max-width: clamp(720px, 78vw, 960px);
  color: var(--text-mid);
  font-size: 12.5px;
  letter-spacing: 0.02em;
  user-select: none;
  pointer-events: none;
}
.streaming-bar.expanded {
  padding: 10px 32px 12px;
}
.streaming-bar-dots {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.streaming-bar-dots span {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent);
  opacity: 0.35;
  animation: streaming-dot 1.2s infinite ease-in-out;
}
.streaming-bar-dots span:nth-child(2) {
  animation-delay: 0.15s;
}
.streaming-bar-dots span:nth-child(3) {
  animation-delay: 0.3s;
}
@keyframes streaming-dot {
  0%, 80%, 100% { opacity: 0.35; transform: translateY(0); }
  40% { opacity: 1; transform: translateY(-3px); }
}
.streaming-bar-label {
  font-weight: 500;
  color: var(--text-mute);
}

.active-bar {
  padding: 0 32px;
  background: var(--fade);
}
.active-bar.expanded {
  position: fixed;
  top: 36px;
  left: 0;
  right: 0;
  z-index: 60;
  padding: 0;
  background: var(--bg);
  border-bottom: 1px solid var(--border-faint);
}
.active-bar-inner {
  max-width: clamp(720px, 78vw, 960px);
  margin: 0 auto;
  padding: 6px 0;
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
  color: var(--text-mid);
  flex-wrap: wrap;
}
.active-label {
  font-weight: 500;
  flex-shrink: 0;
}
.active-chips {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  min-width: 0;
}
.active-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 4px 2px 8px;
  border-radius: 999px;
  background: var(--bg);
  border: 1px solid var(--border);
  font-size: var(--app-font-size, 12px);
  color: var(--text);
}
.active-chip.mcp-chip {
  border-color: #16a34a;
  background: rgba(22, 163, 74, 0.06);
}
.active-chip.tool-chip {
  border-color: #7c3aed;
  background: rgba(124, 58, 237, 0.06);
}
.chip-x {
  border: 0;
  background: transparent;
  cursor: pointer;
  font-size: var(--app-font-size, 14px);
  line-height: 1;
  color: var(--text-faint);
  padding: 0 4px;
  border-radius: 999px;
  transition: background 100ms ease, color 100ms ease;
}
.chip-x:hover {
  background: var(--bg-hover);
  color: var(--text);
}

/* ── Action buttons ──────────────────────────────────────────────── */
.ax {
  border: 1px solid var(--border);
  background: var(--bg);
  color: var(--text-mid);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  cursor: pointer;
  transition: background 140ms ease, border-color 140ms ease, color 140ms ease, transform 120ms ease;
}
.ax:hover:not(:disabled) {
  background: var(--bg-subtle);
  border-color: var(--border-mid);
  color: var(--text);
}
.ax:active:not(:disabled) {
  transform: scale(0.96);
}
.ax:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.ax-icon {
  width: 32px;
  height: 32px;
  border-radius: 10px;
}

.ax-pill {
  height: 32px;
  padding: 0 10px 0 12px;
  border-radius: 999px;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-mute);
  max-width: 240px;
}
.ax-pill-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 200px;
}
.ax-pill:hover:not(:disabled) {
  border-color: var(--accent);
  background: var(--bg);
  color: var(--text);
}
.ax-pill[aria-expanded="true"] {
  border-color: var(--accent);
  color: var(--text);
  background: var(--bg);
}

.ax-send {
  width: 32px;
  height: 32px;
  border-radius: 999px;
  background: var(--accent);
  color: var(--accent-fg);
  border-color: var(--accent);
}
.ax-send:hover:not(:disabled) {
  background: var(--accent-hover);
  border-color: var(--accent-hover);
  color: var(--accent-fg);
}
.ax-send:disabled {
  background: var(--bg-hover);
  color: var(--border-mid);
  border-color: var(--bg-hover);
  opacity: 1;
}

/* ── Stop button (streaming) ─────────────────────────────────────────
   Same shape as the send button (32 px round) but filled red with a
   small white square inside. The square is drawn as a span so we
   can keep the surrounding button neutral and re-use the existing
   .ax sizing / spacing rules. The hover state deepens the red so
   the user sees the affordance before they commit. */
.ax-stop {
  width: 32px;
  height: 32px;
  border-radius: 999px;
  background: var(--bg);
  color: var(--text);
  border-color: var(--border);
}
.ax-stop:hover {
  background: color-mix(in srgb, #ef4444 14%, var(--bg));
  border-color: #ef4444;
}
.ax-stop .stop-square {
  display: block;
  width: 12px;
  height: 12px;
  border-radius: 3px;
  background: #ef4444;
  /* Match icon centering — the parent uses flex; this is just
     here to keep the dimensions explicit if the parent changes. */
  margin: 0 auto;
  transition: background 120ms ease;
}
.ax-stop:hover .stop-square {
  background: #dc2626;
}

/* ── Model picker popover ─────────────────────────────────────────── */
.model-picker {
  position: relative;
}
.picker-pop {
  position: absolute;
  bottom: calc(100% + 8px);
  left: 0;
  min-width: 240px;
  max-width: 320px;
  max-height: 360px;
  overflow-y: auto;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 6px;
  box-shadow: var(--shadow-hover),
    0 2px 6px rgba(0, 0, 0, 0.06);
  z-index: 30;
}
.picker-empty {
  padding: 16px;
  font-size: 13px;
  color: var(--text-mid);
  text-align: center;
}
.picker-group + .picker-group {
  margin-top: 4px;
}
.picker-group-label {
  padding: 8px 10px 4px;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--text-faint);
}
.picker-item {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 10px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  cursor: pointer;
  font: inherit;
  font-size: 13.5px;
  color: var(--text-mute);
  text-align: left;
  transition: background 100ms ease, color 100ms ease;
}
.picker-item:hover {
  background: var(--bg-hover);
}
.picker-item.selected {
  background: var(--accent);
  color: var(--accent-fg);
}
.picker-item-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}
.picker-item-ctx {
  font-size: 10.5px;
  color: var(--text-faint);
  font-variant-numeric: tabular-nums;
  flex-shrink: 0;
}
.picker-item.selected .picker-item-ctx {
  color: var(--accent-fg);
  opacity: 0.7;
}
.picker-check {
  flex-shrink: 0;
}

/* popover entrance/exit */
.picker-enter-active,
.picker-leave-active {
  transition: opacity 140ms ease, transform 140ms ease;
}
.picker-enter-from,
.picker-leave-to {
  opacity: 0;
  transform: translateY(4px);
}

/* ── Fullscreen overlay ──────────────────────────────────────────── */
.backdrop {
  position: fixed;
  inset: 0;
  background: var(--backdrop);
  z-index: 40;
}
.composer-wrap.expanded {
  position: fixed;
  inset: 0;
  z-index: 50;
  background: var(--bg);
  border-radius: 0;
  box-shadow: none;
  padding: 0;
  display: flex;
  flex-direction: column;
}
.composer-wrap.expanded .composer {
  width: 100%;
  height: 100%;
  margin: 0;
  max-width: none;
  background: transparent;
  border: 0;
  box-shadow: none;
  border-radius: 0;
  padding: 24px 32px;
  display: flex;
  flex-direction: column;
  flex: 1;
  align-self: stretch;
}
.composer-wrap.expanded .composer-input {
  flex: 1;
  width: 100%;
  font-size: var(--app-font-size, 14px);
  line-height: 1.7;
  padding: 24px 28px;
  max-height: none;
  resize: none;
}
.composer-wrap.expanded .actions {
  border-top: 1px solid var(--border-faint);
  padding-top: 12px;
  margin-top: 4px;
  max-width: none;
}
</style>