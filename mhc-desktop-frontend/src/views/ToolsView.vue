<script setup lang="ts">
// Tools management view — mirrors SkillsView / MCPView layout:
// header with import actions, card list, slide-in detail pane.
//
// Import model: customers receive tool packs (folder / zip of
// `tool.py` + optional `manifest.json`) and bulk-import them. The
// inline Python-source form was removed to keep this page in step
// with Skills / MCP — a tool is imported the same way a skill is.

import { computed, onMounted, ref } from "vue"
import { api, type Tool } from "../api/client"
import { useToolsStore } from "../stores/tools"
import Icon from "../components/Icon.vue"
import { ask } from "../lib/confirm"
import { t } from "../i18n"

const store = useToolsStore()

const importing = ref(false)
type StatusLevel = "info" | "success" | "error"
const status = ref<{ level: StatusLevel; message: string } | null>(null)
const toggling = ref<string | null>(null)
const overwrite = ref(false)

function setStatus(level: StatusLevel, message: string) {
  status.value = { level, message }
}
function clearStatus() {
  status.value = null
}

const selected = ref<Tool | null>(null)
const editing = ref(false)
const editName = ref("")
const editModelName = ref("")
const saving = ref(false)

onMounted(() => {
  store.refresh()
})

const items = computed(() => store.items)

async function selectBySlug(slug: string) {
  const found = items.value.find((s) => s.slug === slug)
  if (!found) return
  selected.value = found
  editing.value = false
  editName.value = found.name
  editModelName.value = found.model_name || ""
}

function clearSelection() {
  selected.value = null
  editing.value = false
  clearStatus()
}

async function toggleEnabled(s: Tool) {
  if (toggling.value) return
  toggling.value = s.slug
  try {
    await store.setEnabled(s.slug, !s.enabled)
    if (selected.value?.slug === s.slug) {
      const refreshed = items.value.find((x) => x.slug === s.slug)
      selected.value = refreshed ?? null
    }
  } catch (e) {
    setStatus("error", e instanceof Error ? e.message : String(e))
  } finally {
    toggling.value = null
  }
}

async function removeTool(s: Tool) {
  const ok = await ask({
    title: t("tools.confirmDeleteTitle"),
    message: t("tools.confirmDelete", { name: s.name }),
    tone: "danger",
    confirmLabel: t("common.delete"),
  })
  if (!ok) return
  try {
    await store.remove(s.slug)
    if (selected.value?.slug === s.slug) clearSelection()
    setStatus("success", t("tools.deleted", { name: s.name }))
  } catch (e) {
    setStatus("error", e instanceof Error ? e.message : String(e))
  }
}

async function pickBulkFolder() {
  clearStatus()
  if (!window.mhc?.pickFolder) {
    setStatus("error", t("tools.noPicker"))
    return
  }
  try {
    importing.value = true
    const path = await window.mhc.pickFolder()
    if (!path) return
    const summary = await api.importBulkToolFolder(path, overwrite.value)
    setStatus(bulkLevel(summary), formatBulkSummary(summary) ?? "")
    await store.refresh()
  } catch (e) {
    setStatus("error", e instanceof Error ? e.message : String(e))
  } finally {
    importing.value = false
  }
}

async function pickBulkZip() {
  clearStatus()
  if (!window.mhc?.pickFile) {
    setStatus("error", t("tools.noPicker"))
    return
  }
  try {
    importing.value = true
    const file = await window.mhc.pickFile({
      filters: [{ name: "Tool pack", extensions: ["zip"] }],
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
    const summary = await api.importBulkToolZip(blob, overwrite.value)
    setStatus(bulkLevel(summary), formatBulkSummary(summary) ?? "")
    await store.refresh()
  } catch (e) {
    setStatus("error", e instanceof Error ? e.message : String(e))
  } finally {
    importing.value = false
  }
}

function formatBulkSummary(s: {
  installed: unknown[]
  skipped: { path: string; reason: string }[]
  errors: { path: string; error: string }[]
}): string | null {
  const parts: string[] = []
  if (s.installed.length)
    parts.push(`${t("tools.bulkInstalled")}: ${s.installed.length}`)
  if (s.skipped.length)
    parts.push(`${t("tools.bulkSkipped")}: ${s.skipped.length}`)
  if (s.errors.length)
    parts.push(`${t("tools.bulkErrors")}: ${s.errors.length}`)
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

async function exportTool(s: Tool) {
  try {
    const manifest = await store.fetchExport(s.slug)
    const blob = new Blob([JSON.stringify(manifest, null, 2)], {
      type: "application/json",
    })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = `${s.slug}.tool.json`
    a.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (e) {
    setStatus("error", e instanceof Error ? e.message : String(e))
  }
}

function startEdit() {
  if (!selected.value) return
  editName.value = selected.value.name
  editModelName.value = selected.value.model_name || ""
  editing.value = true
}

function cancelEdit() {
  editing.value = false
  if (selected.value) {
    editName.value = selected.value.name
    editModelName.value = selected.value.model_name || ""
  }
}

async function saveEdit() {
  if (!selected.value) return
  saving.value = true
  clearStatus()
  const body: { name?: string; model_name?: string } = {
    name: editName.value.trim() || selected.value.name,
  }
  body.model_name = editModelName.value.trim()
  try {
    const updated = await store.update(selected.value.slug, body)
    selected.value = updated
    editing.value = false
    await store.refresh()
  } catch (e) {
    setStatus("error", e instanceof Error ? e.message : String(e))
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <section class="page">
    <header class="head">
      <div>
        <h2>{{ t("tools.title") }}</h2>
        <p class="hint">{{ t("tools.hint") }}</p>
      </div>
      <div class="actions">
        <label class="overwrite" :title="t('tools.importOverwrite')">
          <input v-model="overwrite" type="checkbox" />
          <span>{{ t("tools.importOverwrite") }}</span>
        </label>
        <button class="btn-secondary" :disabled="importing" @click="pickBulkFolder">
          <Icon name="package" />
          {{ t("tools.importBulkFolder") }}
        </button>
        <button class="btn-secondary" :disabled="importing" @click="pickBulkZip">
          <Icon name="package" />
          {{ t("tools.importBulkZip") }}
        </button>
      </div>
    </header>

    <p v-if="status" :class="['status-banner', `status-${status.level}`]">
      {{ status.message }}
    </p>
    <p v-if="store.loading && store.items.length === 0" class="loading">
      {{ t("common.loading") }}
    </p>

    <div class="split">
      <ul v-if="items.length > 0" class="list">
        <li
          v-for="s in items"
          :key="s.slug"
          class="card"
          :class="{
            off: !s.enabled,
            selected: selected?.slug === s.slug,
          }"
          @click="selectBySlug(s.slug)"
        >
          <div class="row">
            <div class="grow">
              <div class="title">
                {{ s.name }}
                <span class="origin-badge" :class="`kind-${s.kind}`">
                  {{ t(`tools.kind.${s.kind}`) }}
                </span>
              </div>
              <div class="desc">{{ s.description || t("mcp.noDescription") }}</div>
              <div class="meta">
                <span class="slug">/{{ s.slug }}</span>
                <span v-if="s.model_name" class="model-name">model: {{ s.model_name }}</span>
              </div>
            </div>
            <label
              class="switch"
              :title="s.enabled ? t('skills.disable') : t('skills.enable')"
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
      <p v-else-if="!store.loading" class="muted">{{ t("tools.empty") }}</p>
    </div>

    <Transition name="pane">
      <aside v-if="selected" class="detail" @click.stop>
        <header class="detail-head">
          <div class="grow">
            <h3>
              {{ selected.name }}
              <span class="origin-badge small" :class="`kind-${selected.kind}`">
                {{ t(`tools.kind.${selected.kind}`) }}
              </span>
            </h3>
            <div class="detail-sub">/{{ selected.slug }}</div>
          </div>
          <button class="close" :title="t('common.cancel')" @click="clearSelection">
            <Icon name="x" />
          </button>
        </header>

        <div class="detail-actions">
          <button class="btn-secondary" @click="exportTool(selected)">
            <Icon name="download" />
            {{ t("tools.download") }}
          </button>
          <button class="btn-secondary" @click="startEdit" :disabled="editing">
            <Icon name="edit" />
            {{ t("common.edit") }}
          </button>
          <button class="btn-danger" @click="removeTool(selected)">
            <Icon name="trash" />
            {{ t("common.delete") }}
          </button>
        </div>

        <section class="detail-body">
          <template v-if="!editing">
            <div class="detail-desc">
              {{ selected.description || t("mcp.noDescription") }}
            </div>
            <h4>{{ t("tools.parameters") }}</h4>
            <pre class="params">{{ JSON.stringify(selected.parameters ?? {}, null, 2) }}</pre>
            <template v-if="selected.source_path">
              <h4>{{ t("tools.source") }}</h4>
              <div class="source-path">{{ selected.source_path }}</div>
            </template>
          </template>

          <template v-else>
            <label class="field">
              <span>{{ t("tools.editNameLabel") }}</span>
              <input v-model="editName" type="text" class="ta" />
            </label>
            <label class="field">
              <span>{{ t("tools.editModelNameLabel") }}</span>
              <input
                v-model="editModelName"
                type="text"
                class="ta mono"
                :placeholder="selected.slug"
              />
            </label>
            <div class="edit-actions">
              <button class="btn-secondary" :disabled="saving" @click="cancelEdit">
                {{ t("common.cancel") }}
              </button>
              <button class="btn-primary" :disabled="saving" @click="saveEdit">
                {{ saving ? t("common.saving") : t("common.save") }}
              </button>
            </div>
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
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.overwrite {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-mid);
  cursor: pointer;
  margin-right: 4px;
}
.overwrite input {
  margin: 0;
}
.split {
  flex: 1;
  min-height: 0;
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
.origin-badge.kind-local {
  background: rgba(124, 58, 237, 0.10);
  color: #7c3aed;
}
.origin-badge.kind-script {
  background: rgba(234, 88, 12, 0.10);
  color: #ea580c;
}
.origin-badge.kind-remote {
  background: rgba(37, 99, 235, 0.10);
  color: #2563eb;
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
}
.slug {
  font-family: ui-monospace, "JetBrains Mono", monospace;
}
.model-name {
  font-family: ui-monospace, "JetBrains Mono", monospace;
}

/* Toggle switch */
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

/* Detail pane */
.detail {
  position: fixed;
  top: 36px; /* below TitleBar */
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
.params {
  background: var(--bg-subtle);
  border: 1px solid var(--border-faint);
  border-radius: 8px;
  padding: 12px 14px;
  font-size: 12px;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
  margin: 0;
  max-height: 40vh;
  overflow-y: auto;
  font-family: ui-monospace, "JetBrains Mono", monospace;
}
.source-path {
  font-family: ui-monospace, "JetBrains Mono", monospace;
  font-size: 12px;
  color: var(--text-mid);
  background: var(--bg-subtle);
  border: 1px solid var(--border-faint);
  border-radius: 6px;
  padding: 8px 10px;
  word-break: break-all;
}

/* Edit form */
.field {
  display: block;
  margin-bottom: 14px;
}
.field > span {
  display: block;
  font-size: 12px;
  color: var(--text-mid);
  margin-bottom: 4px;
  font-weight: 500;
}
.ta {
  width: 100%;
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 8px 10px;
  font: inherit;
  font-size: 13px;
  background: var(--bg);
  color: var(--text);
}
.ta:focus {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 2px var(--accent-soft);
}
.ta.mono {
  font-family: ui-monospace, "JetBrains Mono", monospace;
  font-size: 12.5px;
}
.edit-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
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
.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
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
.btn-secondary:disabled {
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

/* Slide-in transition */
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
