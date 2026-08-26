<script setup lang="ts">
import { onMounted, ref } from "vue"
import { api, type Skill, type SkillDetail } from "../api/client"
import { useSkillsStore } from "../stores/skills"
import Icon from "../components/Icon.vue"
import { ask } from "../lib/confirm"
import { t } from "../i18n"

const store = useSkillsStore()

const importing = ref(false)
type StatusLevel = "info" | "success" | "error"
const status = ref<{ level: StatusLevel; message: string } | null>(null)
const toggling = ref<string | null>(null)

function setStatus(level: StatusLevel, message: string) {
  status.value = { level, message }
}
function clearStatus() {
  status.value = null
}

const selected = ref<SkillDetail | null>(null)
const editing = ref(false)
const editDescription = ref("")
const editBody = ref("")
const saving = ref(false)

onMounted(() => {
  store.refresh()
})

async function pickFolder() {
  clearStatus()
  if (!window.mhc?.pickFolder) {
    setStatus("error", t("skills.noPicker"))
    return
  }
  try {
    importing.value = true
    const path = await window.mhc.pickFolder()
    if (!path) return
    const created = await store.importFolder(path)
    const detail = await api.getSkill(created.slug)
    select(detail)
  } catch (e) {
    setStatus("error", e instanceof Error ? e.message : String(e))
  } finally {
    importing.value = false
  }
}

async function pickZip() {
  clearStatus()
  if (!window.mhc?.pickFile) {
    setStatus("error", t("skills.noPicker"))
    return
  }
  try {
    importing.value = true
    const file = await window.mhc.pickFile({
      filters: [{ name: "Skill bundle", extensions: ["zip"] }],
    })
    if (!file) return
    // File path on Windows looks like C:\Users\...\foo.zip — we just need
    // the filename as the slug hint and the bytes themselves.
    const buf = await fetch(`file://${file.path ?? ""}`).catch(() => null)
    let blob: Blob
    if (buf && buf.ok) {
      blob = await buf.blob()
    } else {
      // Fall back: read via electron preload if the browser can't fetch
      // file://. We treat the picker result as having an inline Buffer.
      const raw = await window.mhc.readFile?.(file.path ?? "")
      if (!raw) throw new Error("could not read picked file")
      blob = new Blob([new Uint8Array(raw)])
    }
    const name = file.name || "skill.zip"
    const created = await store.importZip(name, blob)
    const detail = await api.getSkill(created.slug)
    select(detail)
  } catch (e) {
    setStatus("error", e instanceof Error ? e.message : String(e))
  } finally {
    importing.value = false
  }
}

// Bulk import: pick a folder containing many SKILL.md subfolders
// (or a zip of the same shape) and install every one. The backend
// copies each into ~/.mhc-desktop/skills/<slug>/ — we never edit
// the user's source files.
async function pickBulkFolder() {
  clearStatus()
  if (!window.mhc?.pickFolder) {
    setStatus("error", t("skills.noPicker"))
    return
  }
  try {
    importing.value = true
    const path = await window.mhc.pickFolder()
    if (!path) return
    const summary = await api.importBulkSkillFolder(path)
    setStatus(bulkLevel(summary), formatBulkSummary(summary) ?? '')
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
    setStatus("error", t("skills.noPicker"))
    return
  }
  try {
    importing.value = true
    const file = await window.mhc.pickFile({
      filters: [{ name: "Skill pack", extensions: ["zip"] }],
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
    const summary = await api.importBulkSkillZip(blob)
    setStatus(bulkLevel(summary), formatBulkSummary(summary) ?? '')
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
    parts.push(`${t("skills.bulkInstalled")}: ${s.installed.length}`)
  if (s.skipped.length)
    parts.push(`${t("skills.bulkSkipped")}: ${s.skipped.length}`)
  if (s.errors.length)
    parts.push(`${t("skills.bulkErrors")}: ${s.errors.length}`)
  return parts.length ? parts.join(" · ") : null
}

// Tone of the bulk-import banner. Errors dominate — even one bad
// file flips the whole result to red — but a clean install is
// green and a fully-skipped re-import is neutral info.
function bulkLevel(s: {
  installed: unknown[]
  skipped: { path: string; reason: string }[]
  errors: { path: string; error: string }[]
}): StatusLevel {
  if (s.errors.length) return "error"
  if (s.installed.length) return "success"
  return "info"
}

async function select(s: SkillDetail) {
  selected.value = s
  editing.value = false
  editDescription.value = s.description
  editBody.value = s.body
}

async function selectBySlug(slug: string) {
  try {
    const detail = await api.getSkill(slug)
    select(detail)
  } catch (e) {
    setStatus("error", e instanceof Error ? e.message : String(e))
  }
}

function clearSelection() {
  selected.value = null
  editing.value = false
  clearStatus()
}

async function toggleEnabled(s: Skill) {
  if (toggling.value) return
  toggling.value = s.slug
  try {
    await store.setEnabled(s.slug, !s.enabled)
    if (selected.value?.slug === s.slug) {
      const refreshed = await api.getSkill(s.slug)
      selected.value = refreshed
    }
  } catch (e) {
    setStatus("error", e instanceof Error ? e.message : String(e))
  } finally {
    toggling.value = null
  }
}

async function deleteSkill(s: Skill) {
  const ok = await ask({
    title: t("skills.confirmDeleteTitle"),
    message: t("skills.confirmDelete", { name: s.name }),
    tone: "danger",
    confirmLabel: t("common.delete"),
  })
  if (!ok) return
  try {
    await store.remove(s.slug)
    if (selected.value?.slug === s.slug) clearSelection()
    setStatus("success", t("skills.deleted", { name: s.name }))
  } catch (e) {
    setStatus("error", e instanceof Error ? e.message : String(e))
  }
}

function exportSkill(s: Skill) {
  // Direct anchor download — backend sets Content-Disposition.
  const a = document.createElement("a")
  a.href = api.exportSkillUrl(s.slug)
  a.download = `${s.slug}.skill.zip`
  a.click()
}

function startEdit() {
  if (!selected.value) return
  editDescription.value = selected.value.description
  editBody.value = selected.value.body
  editing.value = true
}

function cancelEdit() {
  editing.value = false
  if (selected.value) {
    editDescription.value = selected.value.description
    editBody.value = selected.value.body
  }
}

async function saveEdit() {
  if (!selected.value) return
  saving.value = true
  try {
    await api.updateSkill(selected.value.slug, {
      description: editDescription.value,
      body: editBody.value,
    })
    await store.refresh()
    const detail = await api.getSkill(selected.value.slug)
    selected.value = detail
    editing.value = false
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
        <h2>{{ t("skills.title") }}</h2>
        <p class="hint">{{ t("skills.hint") }}</p>
      </div>
      <div class="actions">
        <button class="btn-secondary" :disabled="importing" @click="pickFolder">
          <Icon name="folder" />
          {{ t("skills.importFolder") }}
        </button>
        <button class="btn-secondary" :disabled="importing" @click="pickZip">
          <Icon name="upload" />
          {{ t("skills.importZip") }}
        </button>
        <button class="btn-secondary" :disabled="importing" @click="pickBulkFolder">
          <Icon name="package" />
          {{ t("skills.importBulkFolder") }}
        </button>
        <button class="btn-secondary" :disabled="importing" @click="pickBulkZip">
          <Icon name="package" />
          {{ t("skills.importBulkZip") }}
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
          @click="selectBySlug(s.slug)"
        >
          <div class="row">
            <div class="grow">
              <div class="title">
                {{ s.name }}
                <span
                  v-if="s.origin === 'imported'"
                  class="origin-badge"
                >{{ t("skills.imported") }}</span>
              </div>
              <div class="desc">{{ s.description || t("skills.noDescription") }}</div>
              <div class="meta">
                <span class="slug">/{{ s.slug }}</span>
                <span v-if="s.files.length > 0" class="files">+ {{ s.files.length }} files</span>
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
      <p v-else-if="!store.loading" class="muted" v-html="t('skills.empty')" />
    </div>

    <!-- Detail pane (slides over on the right when a skill is selected) -->
    <Transition name="pane">
      <aside v-if="selected" class="detail" @click.stop>
        <header class="detail-head">
          <div class="grow">
            <h3>
              {{ selected.name }}
              <span class="origin-badge small">
                {{ t(`skills.${selected.origin}`) }}
              </span>
            </h3>
            <div class="detail-sub">
              /{{ selected.slug }} · {{ selected.files.length }} {{ t("skills.files") }}
            </div>
          </div>
          <button class="close" :title="t('common.cancel')" @click="clearSelection">
            <Icon name="x" />
          </button>
        </header>

        <div class="detail-actions">
          <button class="btn-secondary" @click="exportSkill(selected)">
            <Icon name="download" />
            {{ t("skills.export") }}
          </button>
          <button class="btn-secondary" @click="startEdit" :disabled="editing">
            <Icon name="edit" />
            {{ t("skills.edit") }}
          </button>
          <button class="btn-danger" @click="deleteSkill(selected)">
            <Icon name="trash" />
            {{ t("common.delete") }}
          </button>
        </div>

        <section class="detail-body">
          <template v-if="!editing">
            <div class="detail-desc">{{ selected.description || t("skills.noDescription") }}</div>
            <h4>SKILL.md</h4>
            <pre class="md">{{ selected.body || t("skills.emptyBody") }}</pre>
            <template v-if="selected.files.length > 0">
              <h4>{{ t("skills.files") }}</h4>
              <ul class="filelist">
                <li v-for="f in selected.files" :key="f">
                  <Icon name="file" />
                  <span>{{ f }}</span>
                </li>
              </ul>
            </template>
          </template>

          <template v-else>
            <label class="field">
              <span>{{ t("skills.editDescription") }}</span>
              <textarea
                v-model="editDescription"
                rows="2"
                class="ta"
              />
            </label>
            <label class="field">
              <span>{{ t("skills.editBody") }}</span>
              <textarea
                v-model="editBody"
                rows="20"
                class="ta mono"
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
  gap: 8px;
  flex-shrink: 0;
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
  top: 36px;  /* below TitleBar */
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
  max-height: 50vh;
  overflow-y: auto;
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
  resize: vertical;
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
  line-height: 1.55;
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

/* Slide-in transition for the detail pane */
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
