<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from "vue"
import { api, blobToB64, type MarketSkill, type MarketStory } from "../api/client"
import MarketIcon from "../components/MarketIcon.vue"
import { t, locale } from "../i18n"
import { showToast, friendlyError } from "../lib/toast"
import { marketQuery } from "../lib/market"

const items = ref<MarketSkill[]>([])
const stories = ref<MarketStory[]>([])
const detail = ref<(MarketSkill & { body: string; files: { path: string; content: string }[] }) | null>(null)
const detailLoading = ref(false)
const openStory = ref<MarketStory | null>(null)
// 市场搜索：与顶部导航搜索共享同一关键词源。
const query = marketQuery
const category = ref("")
const sort = ref("downloads")
const loading = ref(false)
const adding = ref<string | null>(null)
const justAdded = ref<string | null>(null)
let justAddedTimer: ReturnType<typeof setTimeout> | null = null

const CATEGORIES = ["efficiency", "writing", "coding", "office", "other"]
const CATEGORY_LABELS: Record<string, string> = {
  efficiency: "cat.efficiency",
  writing: "cat.writing",
  coding: "cat.coding",
  office: "cat.office",
  other: "cat.other",
}
const SORT_OPTIONS = [
  { key: "downloads", labelKey: "market.hot" },
  { key: "newest", labelKey: "market.newest" },
]

function excerpt(content: string): string {
  const c = content.replace(/#{1,4}\s+/g, "").replace(/\*\*/g, "").replace(/\n+/g, " ").trim()
  return c.slice(0, 80) + (c.length > 80 ? "…" : "")
}

async function load() {
  loading.value = true
  try {
    const [res, storyList] = await Promise.all([
      api.listSkills(query.value, category.value, sort.value),
      api.listStories(),
    ])
    items.value = res.items
    stories.value = storyList
  } catch (e) {
    showToast(friendlyError(e instanceof Error ? e.message : String(e)), "error")
  } finally {
    loading.value = false
  }
}

function byCategory(c: string) { category.value = c; load() }
function bySort(k: string) { sort.value = k; load() }
function skillOf(slug: string): MarketSkill | undefined {
  return items.value.find((m) => m.slug === slug)
}
function grading(i: number): string {
  const g = ["linear-gradient(135deg,#2563eb,#7c3aed)", "linear-gradient(135deg,#0ea5e9,#2563eb)", "linear-gradient(135deg,#f59e0b,#f97316)", "linear-gradient(135deg,#10b981,#34d399)", "linear-gradient(135deg,#ec4899,#f472b6)"]
  return g[i % g.length]
}
function fmtDate(ts: number): string {
  return new Date(ts * 1000).toLocaleDateString(locale.value === "zh" ? "zh-CN" : "en-US")
}

// ── 详情弹窗（对齐桌面端：读取 SKILL.md + 文件列表）───────────────
async function openDetail(m: MarketSkill) {
  detailLoading.value = true
  try {
    const files = await api.getSkillFiles(m.slug)
    const skillMd = files.find((f) => f.path.endsWith("SKILL.md"))
    detail.value = { ...m, body: skillMd?.content ?? "", files }
  } catch (e) {
    showToast(friendlyError(e instanceof Error ? e.message : String(e)), "error")
  } finally {
    detailLoading.value = false
  }
}
function closeDetail() { detail.value = null }

function openStoryModal(id: string) {
  const s = stories.value.find((x) => x.id === id)
  if (s) openStory.value = s
}
function closeStory() { openStory.value = null }

let timer: ReturnType<typeof setTimeout> | null = null
function onSearch() { if (timer) clearTimeout(timer); timer = setTimeout(load, 300) }

// ── 添加（无状态：永远可点，成功短暂 ✓ + 友好 toast）──────────────
function flashAdded(slug: string) {
  justAdded.value = slug
  if (justAddedTimer) clearTimeout(justAddedTimer)
  justAddedTimer = setTimeout(() => { justAdded.value = null }, 1600)
}
function addButtonText(slug: string): string {
  if (justAdded.value === slug) return "✓ " + t("market.addedShort")
  return adding.value === slug ? t("market.adding") : t("market.add")
}
function addButtonDone(slug: string): boolean {
  return justAdded.value === slug
}
async function addToCloud(slug: string) {
  if (adding.value === slug) return
  adding.value = slug
  try {
    const { blob, sha } = await api.downloadPublic(slug)
    const b64 = await blobToB64(blob)
    await api.uploadMine(slug, b64, sha)
    flashAdded(slug)
    showToast(t("market.addedToast", { name: skillOf(slug)?.display_name ?? slug }), "success")
  } catch (e) {
    showToast(t("market.addFailed", { detail: friendlyError(e instanceof Error ? e.message : String(e)) }), "error")
  } finally {
    adding.value = null
  }
}

// ESC 依次关闭：详情 → 推荐故事
function onKeydown(e: KeyboardEvent) {
  if (e.key !== "Escape") return
  if (detail.value) closeDetail()
  else if (openStory.value) closeStory()
}

onMounted(() => {
  load()
  window.addEventListener("keydown", onKeydown)
})
onUnmounted(() => {
  window.removeEventListener("keydown", onKeydown)
})
// 顶部导航搜索变化 → 防抖刷新市场列表
watch(query, () => onSearch())
</script>

<template>
  <div>
    <!-- 市场搜索（对齐桌面端市场标签页） -->
    <div class="market-search">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7" /><line x1="21" y1="21" x2="16.65" y2="16.65" /></svg>
      <input
        v-model="query"
        :placeholder="t('market.searchPlaceholder')"
        @input="onSearch"
      />
    </div>

    <div class="section-title"><em>{{ t("todayPick") }}</em> {{ t("story.of") }}</div>
    <div v-if="stories.length" class="stories">
      <div v-for="(s, i) in stories" :key="s.id" class="story" :style="{ background: grading(i) }" @click="openStoryModal(s.id)">
        <div class="eyebrow">{{ skillOf(s.skill_slug)?.display_name ?? s.skill_slug }}</div>
        <h3>{{ s.title }}</h3>
        <p>{{ excerpt(s.content) }}</p>
        <div class="meta">{{ t("market.by") }} {{ s.author }} · {{ fmtDate(s.created_at) }}</div>
      </div>
    </div>

    <div class="hero">
      <h1>{{ t("hero.title") }}</h1>
      <p>{{ t("hero.sub") }}</p>
    </div>

    <div class="filters">
      <div class="chips">
        <span class="chip" :class="{ active: !category }" @click="byCategory('')">{{ t("market.all") }}</span>
        <span v-for="c in CATEGORIES" :key="c" class="chip" :class="{ active: category === c }" @click="byCategory(c)">{{ t(CATEGORY_LABELS[c]) }}</span>
      </div>
      <div class="seg">
        <button v-for="o in SORT_OPTIONS" :key="o.key" :class="{ active: sort === o.key }" @click="bySort(o.key)">{{ t(o.labelKey) }}</button>
      </div>
    </div>

    <div v-if="loading && !items.length" class="grid">
      <div v-for="i in 8" :key="i" class="skill-card skeleton" />
    </div>
    <div v-else-if="items.length" class="grid">
      <div v-for="m in items" :key="m.slug" class="skill-card" @click="openDetail(m)">
        <div class="top">
          <MarketIcon :icon="m.icon" :name="m.display_name" :size="52" />
          <span class="cat">{{ t(CATEGORY_LABELS[m.category] ?? "cat.other") }}</span>
        </div>
        <h3>{{ m.display_name }}</h3>
        <div class="desc">{{ m.description }}</div>
        <div class="foot">
          <div class="stats">
            <span class="dl">⬇ {{ m.downloads }}</span>
            <span class="author">{{ t("market.by") }} {{ m.author }}</span>
          </div>
          <button
            class="btn-add"
            :class="{ done: addButtonDone(m.slug) }"
            :disabled="adding === m.slug"
            @click.stop="addToCloud(m.slug)"
          >{{ addButtonText(m.slug) }}</button>
        </div>
      </div>
    </div>
    <div v-else class="empty">
      <div class="e-icon">🪄</div>
      <h3>{{ t("market.empty.title") }}</h3>
      <p class="muted">{{ t("market.empty.desc") }}</p>
    </div>

    <!-- 技能详情弹窗（对齐桌面端：SKILL.md + 文件列表） -->
    <div v-if="detail" class="dialog-mask" @click.self="closeDetail">
      <div class="story-modal detail-modal">
        <div class="detail-head">
          <div class="dh-main">
            <div class="dh-top">
              <MarketIcon :icon="detail.icon" :name="detail.display_name" :size="48" />
              <div class="grow">
                <h3>{{ detail.display_name }}</h3>
                <div class="faint small">{{ t(CATEGORY_LABELS[detail.category] ?? "cat.other") }} · {{ t("market.by") }} {{ detail.author }} · ⬇ {{ detail.downloads }}</div>
              </div>
            </div>
            <p class="faint">{{ detail.description }}</p>
          </div>
          <button class="btn ghost" @click="closeDetail">✕</button>
        </div>
        <div class="detail-body">
          <div class="section-title" style="margin-top:0">SKILL.md</div>
          <pre class="md">{{ detailLoading ? t("market.loading") : detail.body || t("market.emptyBody") }}</pre>
          <div v-if="detail.files.length > 1" class="section-title">Files</div>
          <ul v-if="detail.files.length > 1" class="filelist">
            <li v-for="f in detail.files" :key="f.path">{{ f.path }}</li>
          </ul>
        </div>
        <div class="detail-foot">
          <button
            class="btn primary"
            :class="{ done: addButtonDone(detail.slug) }"
            :disabled="adding === detail.slug"
            @click="addToCloud(detail.slug)"
          >{{ addButtonText(detail.slug) }}</button>
        </div>
      </div>
    </div>

    <!-- 推荐故事弹窗 -->
    <div v-if="openStory" class="dialog-mask" @click.self="closeStory">
      <div class="story-modal">
        <div class="story-head">
          <div>
            <div class="eyebrow">{{ skillOf(openStory.skill_slug)?.display_name ?? openStory.skill_slug }}</div>
            <h3>{{ openStory.title }}</h3>
            <div class="faint small">{{ t("market.by") }} {{ openStory.author }} · {{ fmtDate(openStory.created_at) }}</div>
          </div>
          <button class="btn ghost" @click="closeStory">✕</button>
        </div>
        <div class="content">{{ openStory.content }}</div>
        <div v-if="skillOf(openStory.skill_slug)" class="linked">
          <MarketIcon :icon="skillOf(openStory.skill_slug)!.icon" :name="skillOf(openStory.skill_slug)!.display_name" :size="44" />
          <div class="grow">
            <b>{{ skillOf(openStory.skill_slug)!.display_name }}</b>
            <div class="faint small">{{ t(CATEGORY_LABELS[skillOf(openStory.skill_slug)!.category] ?? "cat.other") }} · {{ skillOf(openStory.skill_slug)!.downloads }} ↓</div>
          </div>
          <button
            class="btn primary"
            :class="{ done: addButtonDone(openStory.skill_slug) }"
            :disabled="adding === openStory.skill_slug"
            @click="addToCloud(openStory.skill_slug)"
          >{{ addButtonText(openStory.skill_slug) }}</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.hero { text-align: center; padding: 26px 0 20px; }
.hero h1 { font-size: 30px; margin: 0 0 10px; }
.hero p { color: var(--text-mid); margin: 0; font-size: 15px; }
.market-search { display: flex; align-items: center; gap: 8px; background: var(--bg-elev); border: 1px solid var(--border); border-radius: var(--radius-pill); padding: 9px 16px; margin-bottom: 6px; max-width: 480px; color: var(--text-faint); }
.market-search:focus-within { border-color: var(--accent); }
.market-search input { border: 0; background: transparent; font: inherit; font-size: 13.5px; color: var(--text); width: 100%; outline: none; }
.stories { display: flex; gap: 16px; overflow-x: auto; padding: 4px 0 10px; scroll-snap-type: x mandatory; scrollbar-width: thin; }
.story { scroll-snap-align: start; flex: 0 0 380px; border-radius: 18px; padding: 24px; color: #fff; cursor: pointer; box-shadow: var(--shadow-md); transition: transform .18s var(--ease), box-shadow .18s var(--ease); }
.story:hover { transform: translateY(-3px); box-shadow: var(--shadow-lg); }
.story .eyebrow { font-size: 12px; opacity: .9; font-weight: 600; letter-spacing: .04em; margin-bottom: 12px; }
.story h3 { font-size: 20px; margin: 0 0 10px; line-height: 1.3; color: #fff; }
.story p { font-size: 13.5px; opacity: .92; margin: 0 0 14px; line-height: 1.55; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.story .meta { display: flex; gap: 8px; font-size: 12px; opacity: .9; }
.filters { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin: 4px 0 20px; flex-wrap: wrap; }
.chips { display: flex; gap: 8px; flex-wrap: wrap; }
.chip { padding: 8px 16px; font-size: 13px; border: 1px solid var(--border); border-radius: var(--radius-pill); background: var(--bg-elev); color: var(--text-mid); cursor: pointer; font-weight: 500; transition: all .15s ease; }
.chip:hover { border-color: var(--text-faint); color: var(--text); }
.chip.active { background: var(--accent); border-color: var(--accent); color: var(--accent-fg); }
.seg { display: flex; border: 1px solid var(--border); border-radius: var(--radius-btn); overflow: hidden; background: var(--bg-elev); }
.seg button { border: 0; background: transparent; padding: 8px 16px; font-size: 13px; color: var(--text-mid); cursor: pointer; font-weight: 500; transition: background .15s, color .15s; }
.seg button.active { background: var(--accent-soft); color: var(--accent); font-weight: 600; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 18px; }
.skill-card { background: var(--bg-elev); border: 1px solid var(--border); border-radius: var(--radius-card); padding: 20px; display: flex; flex-direction: column; gap: 12px; transition: transform .16s var(--ease), box-shadow .16s var(--ease), border-color .16s; cursor: pointer; }
.skill-card:hover { transform: translateY(-3px); box-shadow: var(--shadow-md); border-color: color-mix(in srgb, var(--accent) 45%, var(--border)); }
.skill-card .top { display: flex; align-items: center; justify-content: space-between; }
.skill-card .cat { font-size: 12px; color: var(--text-mid); background: var(--surface-2); padding: 3px 10px; border-radius: var(--radius-pill); font-weight: 600; }
.skill-card h3 { font-size: 16px; }
.skill-card .desc { font-size: 13px; color: var(--text-mid); line-height: 1.55; min-height: 40px; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.skill-card .foot { display: flex; align-items: center; justify-content: space-between; margin-top: auto; padding-top: 12px; border-top: 1px solid var(--border); }
.stats { display: flex; align-items: center; gap: 10px; font-size: 12px; color: var(--text-faint); }
.stats .dl { font-weight: 600; color: var(--text); }
.stats .author { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 110px; }
.btn-add { background: var(--accent); color: var(--accent-fg); border: 0; border-radius: var(--radius-btn); padding: 8px 14px; font-size: 13px; cursor: pointer; font-weight: 600; transition: background .15s, transform .12s var(--ease); }
.btn-add:hover { background: var(--accent-strong); }
.btn-add:active { transform: scale(.97); }
.btn-add.done { background: var(--bg-elev); color: var(--success); border: 1px solid color-mix(in srgb, var(--success) 40%, var(--border)); }
.btn.primary.done { background: var(--bg-elev); color: var(--success); border: 1px solid color-mix(in srgb, var(--success) 40%, var(--border)); }
.skeleton { background: linear-gradient(90deg, var(--surface-2) 25%, var(--border) 37%, var(--surface-2) 63%); background-size: 400% 100%; animation: shimmer 1.4s ease infinite; cursor: default; }
@keyframes shimmer { 0% { background-position: 100% 50%; } 100% { background-position: 0 50%; } }
.dialog-mask { position: fixed; inset: 0; background: rgba(8,10,14,.5); z-index: 60; display: grid; place-items: center; padding: 24px; backdrop-filter: blur(4px); }
.story-modal { background: var(--bg-elev); border-radius: 20px; width: 680px; max-width: 92vw; max-height: 88vh; overflow-y: auto; padding: 28px; box-shadow: var(--shadow-lg); }
.story-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 16px; }
.story-head .eyebrow { color: var(--accent); font-weight: 600; font-size: 12px; letter-spacing: .04em; margin-bottom: 6px; text-transform: uppercase; }
.story-head h3 { font-size: 22px; margin: 0 0 6px; }
.content { font-size: 14.5px; line-height: 1.85; max-height: 46vh; overflow-y: auto; margin: 0 0 20px; white-space: pre-wrap; color: var(--text); }
.content h4 { margin: 18px 0 8px; }
.linked { display: flex; gap: 12px; align-items: center; background: var(--surface-2); border-radius: 12px; padding: 14px 16px; }
.grow { flex: 1; min-width: 0; }
.small { font-size: 12px; }
.detail-modal { display: flex; flex-direction: column; max-height: 88vh; }
.detail-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 8px; }
.dh-main { flex: 1; min-width: 0; }
.dh-top { display: flex; align-items: center; gap: 12px; margin-bottom: 6px; }
.dh-top h3 { font-size: 20px; }
.detail-body { overflow-y: auto; flex: 1; }
.md { background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px; padding: 12px 14px; font-size: 12.5px; line-height: 1.55; white-space: pre-wrap; word-break: break-word; margin: 0 0 12px; max-height: 46vh; overflow-y: auto; }
.filelist { list-style: none; margin: 0; padding: 0; display: grid; gap: 4px; }
.filelist li { padding: 5px 8px; font-size: 12px; color: var(--text-mid); background: var(--surface-2); border-radius: 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.detail-foot { display: flex; justify-content: flex-end; padding-top: 12px; border-top: 1px solid var(--border); margin-top: 8px; }
</style>
