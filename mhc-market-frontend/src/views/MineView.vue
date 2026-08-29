<script setup lang="ts">
// Personal space (cloud backup of my skills): list + delete.
// Cloud-side only; local↔cloud sync runs in the desktop client.
import { onMounted, computed, ref } from "vue"
import { api, fileToB64, type MySkill } from "../api/client"
import { currentUser } from "../api/auth"
import MarketIcon from "../components/MarketIcon.vue"
import { t, locale } from "../i18n"
import { showToast, friendlyError } from "../lib/toast"

type MineItem = MySkill
const items = ref<MineItem[]>([])
const loading = ref(false)
const uploading = ref(false)
const delisting = ref<string | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
const q = ref("")
const filtered = computed(() => {
  const s = q.value.trim().toLowerCase()
  if (!s) return items.value
  return items.value.filter(
    (x) =>
      (x.display_name || x.slug).toLowerCase().includes(s) ||
      x.slug.toLowerCase().includes(s) ||
      (x.author || "").toLowerCase().includes(s),
  )
})

async function load() {
  loading.value = true
  try {
    // list_user 已按内容 sha 联出市场条目的 display_name / icon /
    // author / market_slug / delisted，无需再拉市场列表匹配。
    items.value = await api.listMine()
  } catch (e) {
    showToast(friendlyError(e instanceof Error ? e.message : String(e)), "error")
  } finally {
    loading.value = false
  }
}

function onPickFile(e: Event) {
  const input = e.target as HTMLInputElement
  const f = input.files?.[0]
  if (f) upload(f)
  input.value = ""
}

async function upload(file: File) {
  uploading.value = true
  try {
    const b64 = await fileToB64(file)
    await api.uploadMine(slugFromName(file.name), b64, "")
    showToast(`${t("mine.upload")}: ${file.name}`, "success")
    await load()
  } catch (e) {
    showToast(friendlyError(e instanceof Error ? e.message : String(e)), "error")
  } finally {
    uploading.value = false
  }
}

function slugFromName(filename: string): string {
  return (
    filename.replace(/\.skill\.zip$|\.zip$/i, "").toLowerCase().replace(/[^a-z0-9-]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 64) || "uploaded-skill"
  )
}

async function remove(slug: string) {
  if (!confirm(`${t("mine.delete")} "${slug}"?`)) return
  try {
    await api.deleteMine(slug)
    showToast(`${t("mine.delete")}: ${slug}`, "success")
    await load()
  } catch (e) {
    showToast(friendlyError(e instanceof Error ? e.message : String(e)), "error")
  }
}

// 下架自己发布的技能：content sha 匹配到自己的市场条目（author==我），
// 用匹配到的市场 key 调公共 delist 端点。副本保留、仅标记，不删云端副本。
async function delist(s: MineItem) {
  if (!s.market_slug) return
  if (!confirm(`${t("mine.delistConfirm")} "${s.display_name || s.slug}"?`)) return
  delisting.value = s.slug
  try {
    await api.delistSkill(s.market_slug)
    showToast(`${t("mine.delistedOk")}: ${s.display_name || s.slug}`, "success")
    await load()
  } catch (e) {
    showToast(friendlyError(e instanceof Error ? e.message : String(e)), "error")
  } finally {
    delisting.value = null
  }
}

function fmtDate(ts: number): string {
  return new Date(ts * 1000).toLocaleString(locale.value === "zh" ? "zh-CN" : "en-US")
}

onMounted(load)
</script>

<template>
  <div>
    <header class="head">
      <div class="head-txt">
        <h2>{{ t("mine.title") }}</h2>
        <p class="muted small">{{ t("mine.sub", { user: currentUser() }) }}</p>
      </div>
      <input ref="fileInput" type="file" accept=".zip" style="display:none" @change="onPickFile" />
      <button class="btn primary" :disabled="uploading" @click="fileInput?.click()">
        {{ uploading ? t("mine.uploading") : t("mine.upload") }}
      </button>
    </header>

    <div class="mine-search">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7" /><line x1="21" y1="21" x2="16.65" y2="16.65" /></svg>
      <input v-model="q" :placeholder="t('mine.search')" />
    </div>

    <div v-if="loading && !filtered.length" class="grid">
      <div v-for="i in 6" :key="i" class="skill-card skeleton" />
    </div>
    <div v-else-if="filtered.length" class="grid">
      <div v-for="s in filtered" :key="s.slug" class="skill-card">
        <div class="top">
          <MarketIcon :icon="s.icon" :name="s.display_name || s.slug" :size="52" />
          <span :class="['badge', s.delisted ? 'orange' : 'gray']">
            {{ s.delisted ? t("mine.delisted") : t("mine.cloudCopy") }}
          </span>
        </div>
        <h3>{{ s.display_name || s.slug }}</h3>
        <div class="meta faint">
          <span>{{ (s.size / 1024).toFixed(1) }} KB</span>
          <span>{{ t("mine.updatedAt") }} {{ fmtDate(s.updated_at) }}</span>
        </div>
        <p v-if="s.delisted" class="delist-hint">{{ t("mine.delistHint") }}</p>
        <div class="row-actions">
          <button
            v-if="s.author && s.author === currentUser() && s.market_slug && !s.delisted"
            class="icon-btn delist"
            :title="t('mine.delist')"
            :disabled="delisting === s.slug"
            @click="delist(s)"
          >
            {{ t("mine.delist") }}
          </button>
          <button class="icon-btn danger" :title="t('mine.delete')" @click="remove(s.slug)">
            <span class="trash">🗑</span>
          </button>
        </div>
      </div>
    </div>
    <div v-else class="empty">
      <div class="e-icon">☁️</div>
      <h3>{{ t("mine.empty.title") }}</h3>
      <p class="muted">{{ t("mine.empty.desc") }}</p>
    </div>
  </div>
</template>

<style scoped>
.head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 16px; }
.head h2 { font-size: 22px; margin: 0 0 4px; }
.small { font-size: 13px; }
.mine-search { display: flex; align-items: center; gap: 8px; background: var(--bg-elev); border: 1px solid var(--border); border-radius: var(--radius-pill); padding: 9px 16px; margin-bottom: 18px; max-width: 360px; color: var(--text-faint); }
.mine-search:focus-within { border-color: var(--accent); }
.mine-search input { border: 0; background: transparent; font: inherit; font-size: 13.5px; color: var(--text); width: 100%; outline: none; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 18px; }
.skill-card { background: var(--bg-elev); border: 1px solid var(--border); border-radius: var(--radius-card); padding: 20px; display: flex; flex-direction: column; gap: 12px; transition: transform .16s var(--ease), box-shadow .16s var(--ease), border-color .16s; }
.skill-card:hover { transform: translateY(-3px); box-shadow: var(--shadow-md); border-color: color-mix(in srgb, var(--accent) 40%, var(--border)); }
.skill-card .top { display: flex; align-items: center; justify-content: space-between; }
.skill-card h3 { font-size: 16px; }
.skill-card .meta { display: flex; gap: 14px; font-size: 12px; }
.skill-card .row-actions { display: flex; justify-content: flex-end; margin-top: auto; padding-top: 12px; border-top: 1px solid var(--border); }
.icon-btn { width: 34px; height: 34px; border-radius: var(--radius-btn); border: 1px solid var(--border); background: var(--bg-elev); color: var(--text-mid); cursor: pointer; display: grid; place-items: center; transition: background .15s, border-color .15s; }
.icon-btn:hover { background: var(--surface-2); border-color: var(--border-strong); }
.icon-btn.danger { color: var(--danger); border-color: color-mix(in srgb, var(--danger) 30%, var(--border)); }
.icon-btn.danger:hover { background: var(--danger-soft); }
.icon-btn.delist { color: #d97706; border-color: color-mix(in srgb, #d97706 40%, var(--border)); font-size: 12px; padding: 0 10px; width: auto; }
.icon-btn:disabled { opacity: 0.5; cursor: default; }
.badge.orange { background: rgba(230, 126, 34, 0.15); color: #d97706; }
.delist-hint { font-size: 12px; line-height: 1.5; color: #b45309; background: rgba(230, 126, 34, 0.08); border: 1px solid rgba(230, 126, 34, 0.3); border-radius: 8px; padding: 8px 10px; margin: 0; }
.trash { font-size: 15px; line-height: 1; }
.skeleton { background: linear-gradient(90deg, var(--surface-2) 25%, var(--border) 37%, var(--surface-2) 63%); background-size: 400% 100%; animation: shimmer 1.4s ease infinite; }
@keyframes shimmer { 0% { background-position: 100% 50%; } 100% { background-position: 0 50%; } }
</style>
