<script setup lang="ts">
import { onMounted, ref, watch } from "vue"
import { useRouter, useRoute } from "vue-router"
import { useSessionsStore } from "../stores/sessions"
import { useSessionStreamsStore } from "../stores/sessionStreams"
import Icon from "./Icon.vue"
import { ask } from "../lib/confirm"
import { t } from "../i18n"

const store = useSessionsStore()
const streams = useSessionStreamsStore()
const router = useRouter()
const route = useRoute()

// Edit mode toggles the multi-select UI. Outside edit mode the list
// is plain: just rows + new-session button. Inside, checkboxes and
// bulk actions (delete selected / clear all) appear.
const editMode = ref(false)
const selected = ref<Set<string>>(new Set())
const renaming = ref<string | null>(null)
const renameDraft = ref("")
const renameInputEl = ref<HTMLInputElement | null>(null)

function enterEdit() {
  editMode.value = true
  selected.value = new Set()
  renaming.value = null
}
function exitEdit() {
  editMode.value = false
  selected.value = new Set()
}

onMounted(() => {
  store.refresh()
})

// When the active session changes (e.g. via chat view, not sidebar
// clicks), leave edit mode if open so the user lands on a clean list.
watch(
  () => store.currentId,
  (id) => {
    if (editMode.value && id) {
      exitEdit()
    }
  },
)

watch(
  () => store.currentId,
  async (id) => {
    if (id && (!store.current || store.current.id !== id)) {
      try {
        await store.select(id)
      } catch {
        // ignored in sidebar
      }
    }
  },
)

async function newSession() {
  selected.value = new Set()
  renaming.value = null
  await store.create()
}

function formatTime(iso: string): string {
  if (!iso) return ""
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ""
  const today = new Date()
  const sameDay =
    d.getFullYear() === today.getFullYear() &&
    d.getMonth() === today.getMonth() &&
    d.getDate() === today.getDate()
  try {
    if (sameDay) {
      return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    }
    return d.toLocaleDateString([], { month: "short", day: "numeric" })
  } catch {
    return sameDay ? d.toTimeString().slice(0, 5) : d.toDateString()
  }
}

async function openSession(id: string) {
  if (editMode.value) {
    toggleSelect(id)
    return
  }
  if (renaming.value) return
  if (route.path !== "/chat") {
    await router.push("/chat")
  }
  await store.select(id)
}

async function remove(id: string, e: Event) {
  e.stopPropagation()
  if (!confirm(t("common.confirmDeleteSession"))) return
  await store.remove(id)
  selected.value.delete(id)
}

function toggleSelect(id: string, e?: Event) {
  if (e) e.stopPropagation()
  const next = new Set(selected.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  selected.value = next
}

const allSelected = (): boolean =>
  store.items.length > 0 && selected.value.size === store.items.length

function toggleSelectAll() {
  if (allSelected()) {
    selected.value = new Set()
  } else {
    selected.value = new Set(store.items.map((s) => s.id))
  }
}

async function deleteSelected() {
  if (selected.value.size === 0) return
  const ids = [...selected.value]
  const ok = await ask({
    title: t("sessions.confirmDeleteTitle"),
    message: t("sessions.confirmDeleteMany", { count: ids.length }),
    tone: "danger",
    confirmLabel: t("common.delete"),
  })
  if (!ok) return
  await store.removeMany(ids)
  selected.value = new Set()
}

async function clearAll() {
  if (store.items.length === 0) return
  const ok = await ask({
    title: t("sessions.confirmDeleteTitle"),
    message: t("sessions.confirmClearAll", { count: store.items.length }),
    tone: "danger",
    confirmLabel: t("common.delete"),
  })
  if (!ok) return
  await store.clearAll()
  exitEdit()
}

function startRename(id: string, currentTitle: string, e: Event) {
  e.stopPropagation()
  renaming.value = id
  renameDraft.value = currentTitle || ""
  setTimeout(() => {
    renameInputEl.value?.focus()
    renameInputEl.value?.select()
  }, 0)
}

async function commitRename(id: string) {
  const next = renameDraft.value.trim()
  renaming.value = null
  if (!next) return
  if (next === (store.items.find((s) => s.id === id)?.title ?? "")) return
  try {
    await store.rename(id, next)
  } catch (e) {
    alert(e instanceof Error ? e.message : String(e))
  }
}

function cancelRename() {
  renaming.value = null
  renameDraft.value = ""
}
</script>

<template>
  <div class="sessions">
    <header class="head">
      <span class="title">
        {{
          editMode
            ? t("sessions.editTitle")
            : t("sessions.title")
        }}
      </span>
      <div class="head-actions">
        <!-- Normal mode: edit toggle + new session. -->
        <template v-if="!editMode">
          <button
            v-if="store.items.length > 0"
            class="ic-btn"
            :title="t('sessions.edit')"
            @click="enterEdit"
          >
            <Icon name="edit" />
          </button>
          <button
            class="ic-btn new"
            @click="newSession"
            :title="t('sessions.new')"
          >
            <Icon name="plus" />
          </button>
        </template>
        <!-- Edit mode: cancel + bulk destructive actions. -->
        <template v-else>
          <button
            class="ic-btn"
            :title="t('sessions.deleteSelected')"
            :disabled="selected.size === 0"
            @click="deleteSelected"
          >
            <Icon name="trash" />
          </button>
          <button
            class="ic-btn danger"
            :title="t('sessions.clearAll')"
            @click="clearAll"
          >
            <Icon name="delete-all" />
          </button>
          <button
            class="ic-btn primary"
            :title="t('sessions.done')"
            @click="exitEdit"
          >
            <Icon name="check" />
          </button>
        </template>
      </div>
    </header>

    <!-- Bulk-select bar: only inside edit mode. -->
    <div v-if="editMode && store.items.length > 0" class="bulk-bar">
      <label class="check">
        <input
          type="checkbox"
          :checked="allSelected()"
          @change="toggleSelectAll"
        />
        <span class="check-box" />
        <span class="bulk-label">
          {{
            selected.size > 0
              ? t("sessions.selectedCount", { count: selected.size })
              : t("sessions.selectAll")
          }}
        </span>
      </label>
    </div>

    <p
      v-if="store.loading && store.items.length === 0"
      class="empty"
    >
      {{ t("common.loading") }}
    </p>
    <p v-else-if="store.items.length === 0" class="empty">
      {{ t("sessions.empty") }}
    </p>

    <ul class="list">
      <li
        v-for="s in store.items"
        :key="s.id"
        :class="{
          active: s.id === store.currentId,
          selected: selected.has(s.id),
          renaming: renaming === s.id,
        }"
        @click="openSession(s.id)"
      >
        <label
          v-if="editMode"
          class="check row-check"
          @click.stop
        >
          <input
            type="checkbox"
            :checked="selected.has(s.id)"
            @change="(e) => toggleSelect(s.id, e)"
          />
          <span class="check-box" />
        </label>
        <div class="body">
          <div class="row">
            <!-- Live indicator: pulsing dot while this session's
                 stream is running, so a user browsing other sessions
                 can see at a glance which ones are still working.
                 The bus owns the state, so this updates even when
                 the chat view is showing another session. -->
            <span
              v-if="streams.isStreaming(s.id)"
              class="live"
              :title="t('sessions.running')"
            >
              <span class="live-dot" aria-hidden="true" />
            </span>
            <input
              v-if="renaming === s.id"
              ref="renameInputEl"
              v-model="renameDraft"
              class="rename-input"
              @click.stop
              @keydown.enter.prevent="commitRename(s.id)"
              @keydown.esc.prevent="cancelRename"
              @blur="commitRename(s.id)"
            />
            <div
              v-else
              class="t"
              @dblclick="(e) => startRename(s.id, s.title, e)"
              :title="t('sessions.renameTitle')"
            >
              {{ s.title || t("sessions.new") }}
            </div>
            <button
              v-if="!editMode"
              class="del"
              @click="(e) => remove(s.id, e)"
              :title="t('sessions.delete')"
            >
              ×
            </button>
          </div>
          <div class="meta">
            <span v-if="s.provider">{{ s.provider }}</span>
            <span class="dot">·</span>
            <span>{{ formatTime(s.updated_at) }}</span>
          </div>
        </div>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.sessions {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-panel);
  border-left: 1px solid var(--border);
}
.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 16px 12px;
  border-bottom: 1px solid var(--border);
}
.title {
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-mid);
}
.head-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}
.ic-btn {
  width: 28px;
  height: 28px;
  border-radius: 6px;
  border: 1px solid var(--border-mid);
  background: var(--bg);
  cursor: pointer;
  color: var(--text-mute);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  line-height: 1;
  transition: background 120ms ease, border-color 120ms ease, color 120ms ease;
}
.ic-btn:hover:not(:disabled) {
  background: var(--bg-hover);
  border-color: var(--text-faint);
  color: var(--text);
}
.ic-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.ic-btn.danger:hover:not(:disabled) {
  color: var(--danger);
  border-color: var(--danger-border);
}
.ic-btn.primary:hover:not(:disabled) {
  color: var(--accent);
  border-color: var(--accent);
}
.new {
  /* When this carries an Icon SVG, font-size doesn't matter; we keep
   * the rule for parity with .ic-btn (no font overrides). */
}
.bulk-bar {
  padding: 8px 16px;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  font-size: 11.5px;
  color: var(--text-mid);
}
.bulk-label {
  margin-left: 6px;
}
.empty {
  margin: 16px;
  color: var(--text-faint);
  font-size: 13px;
  line-height: 1.5;
}
.list {
  list-style: none;
  margin: 0;
  padding: 8px;
  overflow-y: auto;
  flex: 1;
}
.list li {
  padding: 10px 12px;
  border-radius: 8px;
  margin-bottom: 2px;
  cursor: pointer;
  transition: background 120ms ease;
  border: 1px solid transparent;
  display: flex;
  align-items: flex-start;
  gap: 8px;
}
.list li:hover {
  background: var(--bg-hover);
}
.list li.active {
  background: var(--bg);
  border-color: var(--border);
}
.list li.selected {
  background: var(--accent-soft);
  border-color: var(--accent);
}
.list li.selected.active {
  background: var(--bg);
  border-color: var(--accent);
}
.body {
  min-width: 0;
  flex: 1;
}
.row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.t {
  font-size: 13.5px;
  font-weight: 500;
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  min-width: 0;
  cursor: text;
}
.rename-input {
  font: inherit;
  font-size: 13.5px;
  font-weight: 500;
  color: var(--text);
  background: var(--bg);
  border: 1px solid var(--accent);
  border-radius: 4px;
  padding: 2px 6px;
  flex: 1;
  min-width: 0;
  outline: none;
}
.del {
  opacity: 0;
  background: transparent;
  border: 0;
  cursor: pointer;
  font-size: 16px;
  color: var(--text-faint);
  padding: 0 4px;
}
.list li:hover .del {
  opacity: 1;
}
.del:hover {
  color: var(--danger);
}

/* Live “running” indicator. A small pulsing dot at the row's left
   edge; the pulse is subtle so the row keeps its calm, static look
   except for the one dot. --accent keeps it on-brand in both themes. */
.live {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 12px;
  height: 14px;
  margin-top: 2px;
  flex-shrink: 0;
}
.live-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--accent);
  animation: live-pulse 1.4s ease-in-out infinite;
}
@keyframes live-pulse {
  0%,
  100% {
    opacity: 1;
    transform: scale(1);
  }
  50% {
    opacity: 0.35;
    transform: scale(0.8);
  }
}
.meta {
  margin-top: 4px;
  font-size: 11.5px;
  color: var(--text-mid);
  display: flex;
  gap: 4px;
}
.dot {
  color: var(--border-mid);
}

/* Selection checkbox (shared with bulk-bar) */
.check {
  display: inline-flex;
  align-items: center;
  cursor: pointer;
  flex-shrink: 0;
  position: relative;
}
.check input {
  position: absolute;
  opacity: 0;
  width: 0;
  height: 0;
}
.check-box {
  width: 16px;
  height: 16px;
  border-radius: 4px;
  border: 1px solid var(--border-mid);
  background: var(--bg);
  display: inline-block;
  position: relative;
  transition: background 120ms ease, border-color 120ms ease;
}
.check:hover .check-box {
  border-color: var(--text-faint);
}
.check input:checked + .check-box {
  background: var(--accent);
  border-color: var(--accent);
}
.check input:checked + .check-box::after {
  content: "";
  position: absolute;
  left: 4.5px;
  top: 1px;
  width: 5px;
  height: 9px;
  border: solid var(--accent-fg);
  border-width: 0 2px 2px 0;
  transform: rotate(45deg);
}
.row-check {
  margin-top: 2px;
}
</style>