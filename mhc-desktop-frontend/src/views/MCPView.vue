<script setup lang="ts">
import { onMounted, ref } from "vue"
import { useMCPsStore } from "../stores/mcps"
import { api, type MCPServer } from "../api/client"
import Icon from "../components/Icon.vue"
import { ask } from "../lib/confirm"
import { t } from "../i18n"

const store = useMCPsStore()

const adding = ref(false)
const addingFresh = ref(false)
type StatusLevel = "info" | "success" | "error"
const status = ref<{ level: StatusLevel; message: string } | null>(null)
function setStatus(level: StatusLevel, message: string) { status.value = { level, message } }
function clearStatus() { status.value = null }
const toggling = ref<string | null>(null)

const selected = ref<MCPServer | null>(null)
const editing = ref(false)
const editName = ref("")
const editDescription = ref("")
const editCommand = ref("")
const editArgs = ref("")
const editEnv = ref("")
const refreshing = ref<string | null>(null)

onMounted(() => {
  store.refresh()
})

async function toggleEnabled(s: MCPServer) {
  if (toggling.value) return
  toggling.value = s.slug
  try {
    await store.setEnabled(s.slug, !s.enabled)
    if (selected.value?.slug === s.slug) {
      const refreshed = await api.getMCP(s.slug)
      selected.value = refreshed
    }
  } catch (e) {
    setStatus("error", e instanceof Error ? e.message : String(e))
  } finally {
    toggling.value = null
  }
}

async function deleteServer(s: MCPServer) {
  const ok = await ask({
    title: t("mcp.confirmDeleteTitle"),
    message: t("mcp.confirmDelete", { name: s.name }),
    tone: "danger",
    confirmLabel: t("common.delete"),
  }); if (!ok) return
  try {
    await store.remove(s.slug)
    if (selected.value?.slug === s.slug) clearSelection()
    setStatus("success", t("mcp.deleted", { name: s.name }))
  } catch (e) {
    setStatus("error", e instanceof Error ? e.message : String(e))
  }
}

async function refreshTools(s: MCPServer) {
  refreshing.value = s.slug
  try {
    const r = await api.refreshMCPTools(s.slug)
    // Pull the server back so its ``tools`` field is fresh.
    const refreshed = await api.getMCP(s.slug)
    store.replace(refreshed)
    if (selected.value?.slug === s.slug) {
      selected.value = refreshed
    }
    if (!r.tools.length) {
      setStatus("error", t("mcp.noToolsReturned"))
    }
  } catch (e) {
    setStatus("error", e instanceof Error ? e.message : String(e))
  } finally {
    refreshing.value = null
  }
}

function clearSelection() {
  selected.value = null
  editing.value = false
  clearStatus()
}

/** Open the edit dialog pre-filled with the selected server. */
function startEdit() {
  const s = selected.value
  if (!s) return
  adding.value = true
  addingFresh.value = false
  editing.value = true
  editName.value = s.name
  editDescription.value = s.description || ""
  editCommand.value = s.command
  editArgs.value = (s.args || []).join(" ")
  editEnv.value = Object.entries(s.env || {})
    .map(([k, v]) => `${k}=${v}`)
    .join("\n")
}

async function exportServer(s: MCPServer) {
  try {
    const blob = await api.exportMCP(s.slug)
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = `${s.slug}.mcp.json`
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    setStatus("error", e instanceof Error ? e.message : String(e))
  }
}

function startAdd() {
  adding.value = true
  addingFresh.value = true
  editing.value = true
  editName.value = ""
  editDescription.value = ""
  editCommand.value = ""
  editArgs.value = ""
  editEnv.value = ""
}

// Bulk-import: pick a folder containing many MCP subfolders (each
// with a config.json describing the spawn vector) and install them
// all. The backend copies each into ~/.mhc-desktop/mcp/<slug>/ so
// the user's source files are never mutated.
async function pickBulkFolder() {
  clearStatus()
  if (!window.mhc?.pickFolder) {
    setStatus("error", t("mcp.noPicker"))
    return
  }
  try {
    adding.value = true
    const path = await window.mhc.pickFolder()
    if (!path) return
    const summary = await api.importBulkMcpFolder(path)
    setStatus(bulkLevel(summary), formatBulkSummary(summary) ?? '')
    await store.refresh()
  } catch (e) {
    setStatus("error", e instanceof Error ? e.message : String(e))
  } finally {
    adding.value = false
  }
}

async function pickBulkZip() {
  clearStatus()
  if (!window.mhc?.pickFile) {
    setStatus("error", t("mcp.noPicker"))
    return
  }
  try {
    adding.value = true
    const file = await window.mhc.pickFile({
      filters: [{ name: "MCP pack", extensions: ["zip"] }],
    })
    if (!file) return
    const buf = await fetch(`file://${file.path ?? ""}`).catch(() => null)
    let blob: Blob
    if (buf && buf.ok) {
      blob = await buf.blob()
    } else {
      const raw = await window.mhc.readFile?.(file.path ?? "")
      if (!raw) throw new Error("could not read picked file")
      blob = new Blob([new Uint8Array(raw)])
    }
    const summary = await api.importBulkMcpZip(blob)
    setStatus(bulkLevel(summary), formatBulkSummary(summary) ?? '')
    await store.refresh()
  } catch (e) {
    setStatus("error", e instanceof Error ? e.message : String(e))
  } finally {
    adding.value = false
  }
}

function formatBulkSummary(s: {
  installed: unknown[]
  skipped: { path: string; reason: string }[]
  errors: { path: string; error: string }[]
}): string | null {
  const parts: string[] = []
  if (s.installed.length)
    parts.push(`${t("mcp.bulkInstalled")}: ${s.installed.length}`)
  if (s.skipped.length)
    parts.push(`${t("mcp.bulkSkipped")}: ${s.skipped.length}`)
  if (s.errors.length)
    parts.push(`${t("mcp.bulkErrors")}: ${s.errors.length}`)
  return parts.length ? parts.join(" · ") : null
}

function bulkLevel(s: {
  installed: unknown[]
  skipped: { path: string; reason: string }[]
  errors: { path: string; error: string }[]
}): StatusLevel {
  if (s.errors.length) return "error"
  if (s.installed.length) return "success"
  return "info"
}

function cancelEdit() {
  adding.value = false
  addingFresh.value = false
  editing.value = false
}

async function saveNew() {
  clearStatus()
  const cmd = editCommand.value.trim()
  if (!cmd) {
    setStatus("error", t("mcp.commandRequired"))
    return
  }
  const args = editArgs.value
    .split(/\s+/)
    .map((a) => a.trim())
    .filter(Boolean)
  const env: Record<string, string> = {}
  for (const line of editEnv.value.split(/\n/)) {
    const trimmed = line.trim()
    if (!trimmed || trimmed.startsWith("#")) continue
    const eq = trimmed.indexOf("=")
    if (eq <= 0) continue
    env[trimmed.slice(0, eq).trim()] = trimmed.slice(eq + 1).trim()
  }
  // When a server is selected and we opened the edit dialog,
  // a slug exists — that's an edit, not a create.
  const editingExisting = !!selected.value && !addingFresh.value
  try {
    let created: MCPServer
    if (editingExisting && selected.value) {
      created = await api.updateMCP(selected.value.slug, {
        name: editName.value.trim() || cmd.split(/\s+/)[0] || "MCP",
        description: editDescription.value.trim(),
        command: cmd,
        args,
        env,
      })
      store.upsertItem(created)
    } else {
      created = await store.upsert({
        name: editName.value.trim() || cmd.split(/\s+/)[0] || "MCP",
        description: editDescription.value.trim(),
        command: cmd,
        args,
        env,
        origin: "imported",
      })
    }
    adding.value = false
    editing.value = false
    selected.value = created
  } catch (e) {
    setStatus("error", e instanceof Error ? e.message : String(e))
  }
}
</script>

<template>
  <section class="page">
    <header class="head">
      <div>
        <h2>{{ t("mcp.title") }}</h2>
        <p class="hint">{{ t("mcp.hint") }}</p>
      </div>
      <div class="actions">
        <button class="btn-primary" @click="startAdd" :disabled="adding">
          <Icon name="plus" />
          {{ t("mcp.add") }}
        </button>
        <button class="btn-secondary" :disabled="adding" @click="pickBulkFolder">
          <Icon name="folder" />
          {{ t("mcp.importBulkFolder") }}
        </button>
        <button class="btn-secondary" :disabled="adding" @click="pickBulkZip">
          <Icon name="package" />
          {{ t("mcp.importBulkZip") }}
        </button>
      </div>
    </header>

    <p v-if="status" :class="['status-banner', `status-${status.level}`]">
      {{ status.message }}
    </p>
    <p
      v-if="store.loading && store.items.length === 0"
      class="loading"
    >
      {{ t("common.loading") }}
    </p>

    <div class="split">
      <ul v-if="store.items.length > 0" class="list">
        <li
          v-for="s in store.items"
          :key="s.slug"
          class="card"
          :class="{
            off: !s.enabled,
            selected: selected?.slug === s.slug,
          }"
          @click="selected = s"
        >
          <div class="row">
            <div class="grow">
              <div class="title">
                {{ s.name }}
                <span v-if="s.origin === 'imported'" class="origin-badge">
                  {{ t("mcp.imported") }}
                </span>
              </div>
              <div class="desc">{{ s.description || t("mcp.noDescription") }}</div>
              <div class="meta">
                <span class="slug">{{ s.command }} {{ s.args.join(" ") }}</span>
                <span v-if="s.tools.length > 0" class="files">
                  + {{ s.tools.length }} tools
                </span>
                <span v-else-if="s.last_error" class="error-text">
                  {{ s.last_error }}
                </span>
              </div>
            </div>
            <label
              class="switch"
              :title="s.enabled ? t('mcp.disable') : t('mcp.enable')"
              @click.stop
            >
              <input
                type="checkbox"
                :checked="s.enabled"
                :disabled="toggling === s.slug"
                @change="toggleEnabled(s)"
              />
              <span class="slider" />
            </label>
          </div>
        </li>
      </ul>
      <p
        v-else-if="!store.loading"
        class="muted"
        v-html="t('mcp.empty')"
      />
    </div>

    <!-- Add modal -->
    <div
      v-if="adding"
      class="modal-bg"
      @click.self="cancelEdit"
    >
      <div class="modal">
        <h3>{{ addingFresh ? t("mcp.addTitle") : t("mcp.editTitle") }}</h3>
        <p class="modal-hint">{{ t("mcp.addHint") }}</p>
        <label class="field">
          <span>{{ t("mcp.name") }}</span>
          <input v-model="editName" :placeholder="t('mcp.namePlaceholder')" />
        </label>
        <label class="field">
          <span>{{ t("mcp.description") }}</span>
          <input v-model="editDescription" />
        </label>
        <label class="field">
          <span>{{ t("mcp.command") }}</span>
          <input
            v-model="editCommand"
            :placeholder="t('mcp.commandPlaceholder')"
          />
        </label>
        <label class="field">
          <span>{{ t("mcp.args") }}</span>
          <input
            v-model="editArgs"
            :placeholder="t('mcp.argsPlaceholder')"
          />
        </label>
        <label class="field">
          <span>{{ t("mcp.env") }}</span>
          <textarea
            v-model="editEnv"
            rows="3"
            :placeholder="t('mcp.envPlaceholder')"
          />
        </label>
        <div class="edit-actions">
          <button class="btn-secondary" @click="cancelEdit">
            {{ t("common.cancel") }}
          </button>
          <button class="btn-primary" @click="saveNew">
            {{ t("common.save") }}
          </button>
        </div>
      </div>
    </div>

    <!-- Detail panel -->
    <Transition name="pane">
      <aside v-if="selected" class="detail" @click.stop>
        <header class="detail-head">
          <div class="grow">
            <h3>
              {{ selected.name }}
              <span class="origin-badge small">
                {{ t(`mcp.${selected.origin}`) }}
              </span>
            </h3>
            <div class="detail-sub">
              /{{ selected.slug }} · {{ selected.tools.length }} tools
            </div>
          </div>
          <button class="close" :title="t('common.cancel')" @click="clearSelection">
            <Icon name="x" />
          </button>
        </header>

        <div class="detail-actions">
          <button
            class="btn-secondary"
            :disabled="refreshing === selected.slug"
            @click="refreshTools(selected)"
          >
            <Icon name="refresh" />
            {{ refreshing === selected.slug ? t("mcp.refreshing") : t("mcp.refreshTools") }}
          </button>
          <button
            class="btn-secondary"
            :disabled="adding"
            @click="startEdit"
          >
            <Icon name="edit" />
            {{ t("common.edit") }}
          </button>
          <button class="btn-secondary" @click="exportServer(selected)">
            <Icon name="download" />
            {{ t("mcp.export") }}
          </button>
          <button class="btn-danger" @click="deleteServer(selected)">
            <Icon name="trash" />
            {{ t("common.delete") }}
          </button>
        </div>

        <section class="detail-body">
          <div class="detail-desc">{{ selected.description || t("mcp.noDescription") }}</div>
          <h4>{{ t("mcp.spawn") }}</h4>
          <pre class="md">{{ selected.command }} {{ selected.args.join(" ") }}</pre>

          <h4>{{ t("mcp.tools") }} ({{ selected.tools.length }})</h4>
          <ul v-if="selected.tools.length > 0" class="filelist">
            <li v-for="tool in selected.tools" :key="tool.name">
              <Icon name="file" />
              <span>{{ tool.name }} — {{ tool.description || t("mcp.noDescription") }}</span>
            </li>
          </ul>
          <p v-else class="muted small">
            {{ t("mcp.noToolsYet") }}
          </p>

          <template v-if="Object.keys(selected.env).length > 0">
            <h4>{{ t("mcp.envLabel") }}</h4>
            <pre class="md">{{ Object.entries(selected.env).map(([k, v]) => `${k}=${v}`).join("\n") }}</pre>
          </template>
        </section>
      </aside>
    </Transition>
  </section>
</template>

<style scoped>
.page {
  position: relative;
  display: flex;
  flex-direction: column;
  max-width: 880px;
  height: 100%;
  margin: 0 auto;
  padding: 32px 24px;
  color: var(--text);
  overflow-y: auto;
}
.head {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 12px;
  margin-bottom: 16px;
}
.head h2 {
  margin: 0 0 4px;
  font-size: 22px;
  letter-spacing: -0.01em;
}
.hint {
  margin: 0;
  color: var(--text-mid);
  font-size: 13px;
  max-width: 540px;
  line-height: 1.5;
}
.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  flex-shrink: 0;
}
.error {
  color: var(--danger);
  background: var(--danger-bg);
  border: 1px solid var(--danger-border);
  border-radius: 8px;
  padding: 8px 12px;
  font-size: 13px;
}
.status-banner {
  border-radius: 8px;
  padding: 8px 12px;
  font-size: 13px;
  border: 1px solid transparent;
}
.status-banner.status-error {
  color: var(--danger);
  background: var(--danger-bg);
  border-color: var(--danger-border);
}
.status-banner.status-success {
  color: var(--success, #15803d);
  background: var(--success-bg, rgba(34, 197, 94, 0.10));
  border-color: var(--success-border, rgba(34, 197, 94, 0.30));
}
.status-banner.status-info {
  color: var(--text-mid);
  background: var(--bg-subtle, var(--bg));
  border-color: var(--border);
}
.loading,
.muted {
  color: var(--text-mid);
  margin: 12px 0;
}
.muted.small { font-size: 12px; }
.error-text { color: var(--danger); }
.list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: grid;
  gap: 8px;
}
.card {
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 14px 16px;
  background: var(--bg);
  cursor: pointer;
  transition: border-color 120ms ease, background 120ms ease, opacity 120ms ease;
}
.card:hover {
  border-color: var(--border-mid);
}
.card.selected {
  border-color: var(--accent);
  box-shadow: 0 0 0 2px var(--accent-soft);
}
.card.off {
  opacity: 0.55;
  background: var(--bg-panel);
}
.row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}
.grow {
  min-width: 0;
  flex: 1;
}
.title {
  font-weight: 600;
  font-size: 14.5px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.origin-badge {
  font-size: 10px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  background: var(--bg-hover);
  padding: 2px 6px;
  border-radius: 4px;
  font-weight: 600;
  color: var(--text-mid);
}
.origin-badge.small {
  font-size: 9px;
  padding: 1px 6px;
}
.desc {
  font-size: 13px;
  color: var(--text-mid);
  margin-top: 4px;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.meta {
  margin-top: 6px;
  font-size: 11.5px;
  color: var(--text-faint);
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}
.slug {
  font-family: ui-monospace, "JetBrains Mono", monospace;
}
.files { color: var(--text-mute); }

/* Toggle */
.switch {
  position: relative;
  display: inline-block;
  width: 32px;
  height: 18px;
  flex-shrink: 0;
  cursor: pointer;
  margin-top: 2px;
}
.switch input {
  opacity: 0;
  width: 0;
  height: 0;
  position: absolute;
}
.slider {
  position: absolute;
  inset: 0;
  background: var(--border);
  border-radius: 999px;
  transition: background 140ms ease;
}
.slider::before {
  content: "";
  position: absolute;
  width: 14px;
  height: 14px;
  left: 2px;
  top: 2px;
  background: var(--bg);
  border-radius: 50%;
  box-shadow: var(--shadow-toggle);
  transition: transform 140ms ease;
}
.switch input:checked + .slider {
  background: var(--accent);
}
.switch input:checked + .slider::before {
  transform: translateX(14px);
}
.switch input:disabled + .slider {
  opacity: 0.5;
}

/* Modal */
.modal-bg {
  position: fixed;
  inset: 0;
  background: var(--backdrop);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 10;
}
.modal {
  background: var(--bg);
  border-radius: 14px;
  padding: 24px;
  width: min(540px, 92vw);
  box-shadow: var(--shadow-strong);
}
.modal h3 {
  margin: 0 0 6px;
  font-size: 16px;
}
.modal-hint {
  margin: 0 0 16px;
  font-size: 12.5px;
  color: var(--text-mid);
  line-height: 1.5;
}
.field {
  display: block;
  margin-bottom: 12px;
}
.field > span {
  display: block;
  font-size: 12px;
  color: var(--text-mid);
  margin-bottom: 4px;
  font-weight: 500;
}
.field input,
.field textarea {
  width: 100%;
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 8px 10px;
  font: inherit;
  font-size: 13px;
  background: var(--bg);
  color: var(--text);
}
.field textarea {
  resize: vertical;
  font-family: ui-monospace, "JetBrains Mono", monospace;
}
.field input:focus,
.field textarea:focus {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 2px var(--accent-soft);
}
.edit-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
  margin-top: 8px;
}

/* Detail */
.detail {
  position: fixed;
  top: 36px;
  right: 0;
  bottom: 0;
  width: min(560px, 60vw);
  background: var(--bg);
  border-left: 1px solid var(--border);
  box-shadow: -8px 0 24px rgba(0, 0, 0, 0.08);
  z-index: 20;
  display: flex;
  flex-direction: column;
}
.detail-head {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-faint);
}
.detail-head h3 {
  margin: 0;
  font-size: 16px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.detail-sub {
  margin-top: 4px;
  font-size: 12px;
  color: var(--text-mid);
}
.close {
  background: transparent;
  border: 0;
  cursor: pointer;
  color: var(--text-mid);
  padding: 4px;
  border-radius: 6px;
  transition: background 120ms ease, color 120ms ease;
}
.close:hover {
  background: var(--bg-hover);
  color: var(--text);
}
.detail-actions {
  display: flex;
  gap: 6px;
  padding: 10px 20px;
  border-bottom: 1px solid var(--border-faint);
}
.detail-body {
  padding: 16px 20px 24px;
  overflow-y: auto;
  flex: 1;
}
.detail-body h4 {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--text-faint);
  font-weight: 600;
  margin: 18px 0 8px;
}
.detail-desc {
  font-size: 13px;
  color: var(--text-mid);
  line-height: 1.6;
}
.md {
  background: var(--bg-subtle);
  border: 1px solid var(--border-faint);
  border-radius: 8px;
  padding: 12px 14px;
  font-size: 12.5px;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
  margin: 0;
  font-family: ui-monospace, "JetBrains Mono", monospace;
}
.filelist {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 4px;
}
.filelist li {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 8px;
  font-size: 12px;
  color: var(--text-mid);
  background: var(--bg-subtle);
  border-radius: 4px;
  font-family: ui-monospace, "JetBrains Mono", monospace;
}

/* Buttons */
.btn-primary,
.btn-secondary,
.btn-danger {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font: inherit;
  font-size: 13px;
  padding: 6px 12px;
  border-radius: 6px;
  cursor: pointer;
  border: 1px solid transparent;
  transition: background 120ms ease, border-color 120ms ease, color 120ms ease;
}
.btn-primary {
  background: var(--accent);
  color: var(--accent-fg);
  border-color: var(--accent);
}
.btn-primary:hover:not(:disabled) {
  background: var(--accent-hover);
}
.btn-secondary {
  background: var(--bg);
  color: var(--text-mid);
  border-color: var(--border);
}
.btn-secondary:hover:not(:disabled) {
  background: var(--bg-hover);
  color: var(--text);
}
.btn-secondary:disabled,
.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.btn-danger {
  background: var(--bg);
  color: var(--danger);
  border-color: var(--danger-border);
}
.btn-danger:hover {
  background: var(--danger-bg);
}

/* Slide-in */
.pane-enter-active,
.pane-leave-active {
  transition: transform 220ms cubic-bezier(0.4, 0, 0.2, 1), opacity 220ms ease;
}
.pane-enter-from,
.pane-leave-to {
  transform: translateX(20px);
  opacity: 0;
}
</style>