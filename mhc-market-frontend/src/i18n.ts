// 国际化：中英双语。locale 持久化到 localStorage，默认为浏览器语言。
import { computed, ref } from "vue"

export type Locale = "zh" | "en"
const LS_KEY = "mhc-market.locale"

const dict = {
  zh: {} as Record<string, string>,
  en: {} as Record<string, string>,
}

function detect(): Locale {
  const saved = localStorage.getItem(LS_KEY)
  if (saved === "zh" || saved === "en") return saved
  return navigator.language?.toLowerCase().startsWith("zh") ? "zh" : "en"
}

export const locale = ref<Locale>(detect())

export const localeLabel = computed(() => (locale.value === "zh" ? "EN" : "中"))

export function setLocale(l: Locale) {
  locale.value = l
  localStorage.setItem(LS_KEY, l)
}

export function t(key: string, vars?: Record<string, string | number>): string {
  let s = dict[locale.value][key] ?? dict.en[key] ?? key
  if (vars) for (const [k, v] of Object.entries(vars)) s = s.replace(`{${k}}`, String(v))
  return s
}

// zh 词典
Object.assign(dict.zh, {
  "market.title": "mhc 技能市场",
  "nav.market": "市场",
  "nav.mine": "我的技能",
  "nav.search": "搜索技能…",
  "nav.logout": "退出",
  "login.title": "登录",
  "login.sub": "使用桌面端相同的账号",
  "login.username": "账号",
  "login.password": "密码",
  "login.usernameReq": "请输入账号",
  "login.submit": "登录",
  "login.loading": "登录中…",
  "login.demo": "演示账号：",
  "login.kicker": "MHC SKILL MARKET",
  "login.hero": "把好用的技能，\n变成你的。",
  "login.subtext": "发现社区精选技能，一键添加到你的助手，让每一次对话都更专业。",
  "login.perk1": "安全审核，发布即用",
  "login.perk2": "本地 / 云端一键同步",
  "login.perk3": "用户故事，看到真实效果",
  "hero.title": "发现好用的技能",
  "hero.sub": "社区甄选 · 安全审核 · 一键添加",
  "todayPick": "今日推荐",
  "story.of": "用户故事",
  "market.add": "添加",
  "market.added": "✓ 已添加",
  "market.addedShort": "已添加",
  "market.adding": "添加中…",
  "market.addedToast": "已将 “{name}” 添加到我的技能。",
  "market.addFailed": "添加失败：{detail}",
  "market.searchPlaceholder": "搜索技能…",
  "market.emptyBody": "暂无内容",
  "market.all": "全部",
  "market.hot": "热门",
  "market.newest": "最新",
  "market.empty.title": "还没有技能",
  "market.empty.desc": "换个关键词或分类试试，或者分享你的第一个技能。",
  "market.loading": "加载中…",
  "market.by": "作者",
  "market.downloads": "下载",
  "cat.efficiency": "效率",
  "cat.writing": "写作",
  "cat.coding": "编程",
  "cat.office": "办公",
  "cat.other": "其他",
  "mine.title": "我的技能",
  "mine.sub": "{user} 的云端个人空间，桌面端「同步」按钮维护的内容副本。",
  "mine.upload": "上传技能 zip",
  "mine.uploading": "上传中…",
  "mine.download": "下载",
  "mine.publish": "发布",
  "mine.delete": "删除",
  "mine.search": "搜索我的技能…",
  "mine.empty.title": "云端还没有技能副本",
  "mine.empty.desc": "在桌面端添加市场技能或点「同步」，或直接上传一个 zip。",
  "mine.mismatchHint": "看不到预期的技能？确认桌面端登录的账号也是「{user}」——云端副本按账号隔离。",
  "mine.updatedAt": "更新",
  "mine.delisted": "已下架",
  "mine.cloudCopy": "云端副本",
  "mine.delist": "下架",
  "mine.delistConfirm": "下架后将从公共市场移除；已添加副本保留并标记已下架，无法再从市场更新。确定下架",
  "mine.delistedOk": "已下架",
  "mine.delistHint": "该技能已下架：副本保留，但无法再从市场更新。",
  "common.save": "保存",
  "common.saving": "保存中…",
  "common.cancel": "取消",
  "skills.editDescription": "描述（frontmatter）",
  "skills.editBody": "正文（markdown）",
  "mine.edit": "编辑",
  "mine.editTitle": "编辑技能",
  "mine.updated": "已更新",
  "theme.light": "浅色",
  "theme.dark": "深色",
})

// en 词典
Object.assign(dict.en, {
  "market.title": "mhc Skills Market",
  "nav.market": "Market",
  "nav.mine": "My Skills",
  "nav.search": "Search skills…",
  "nav.logout": "Sign out",
  "login.title": "Sign in",
  "login.sub": "Use the same account as the desktop app",
  "login.username": "Username",
  "login.password": "Password",
  "login.usernameReq": "Enter a username",
  "login.submit": "Sign in",
  "login.loading": "Signing in…",
  "login.demo": "Demo accounts:",
  "login.kicker": "MHC SKILL MARKET",
  "login.hero": "Turn good skills\ninto yours.",
  "login.subtext": "Discover community-curated skills, add them to your assistant in one click, and make every conversation smarter.",
  "login.perk1": "Safe-reviewed, publish to use",
  "login.perk2": "One-click local / cloud sync",
  "login.perk3": "User stories, real results",
  "hero.title": "Discover great skills",
  "hero.sub": "Community-curated · safely reviewed · one-click add",
  "todayPick": "Today's picks",
  "story.of": "User stories",
  "market.add": "Add",
  "market.added": "✓ Added",
  "market.addedShort": "Added",
  "market.adding": "Adding…",
  "market.addedToast": "Added \"{name}\" to My Skills.",
  "market.addFailed": "Add failed: {detail}",
  "market.searchPlaceholder": "Search skills…",
  "market.emptyBody": "Empty",
  "market.all": "All",
  "market.hot": "Popular",
  "market.newest": "Newest",
  "market.empty.title": "No skills yet",
  "market.empty.desc": "Try another keyword or category, or share your first skill.",
  "market.loading": "Loading…",
  "market.by": "by",
  "market.downloads": "downloads",
  "cat.efficiency": "Efficiency",
  "cat.writing": "Writing",
  "cat.coding": "Coding",
  "cat.office": "Office",
  "cat.other": "Other",
  "mine.title": "My Skills",
  "mine.sub": "{user}'s cloud space, backed up by the desktop 'Sync' button.",
  "mine.upload": "Upload skill zip",
  "mine.uploading": "Uploading…",
  "mine.download": "Download",
  "mine.publish": "Publish",
  "mine.delete": "Delete",
  "mine.search": "Search my skills…",
  "mine.empty.title": "No cloud copies yet",
  "mine.empty.desc": "Add skills from the market or hit 'Sync' in the desktop app, or upload a zip.",
  "mine.mismatchHint": "Not seeing what you expect? Make sure the desktop app is signed in as '{user}' too. Cloud copies are per-account.",
  "mine.updatedAt": "Updated",
  "mine.delisted": "Delisted",
  "mine.cloudCopy": "Cloud copy",
  "mine.delist": "Delist",
  "mine.delistConfirm": "Delisting removes it from the public market; existing copies stay but are flagged delisted and can no longer be updated from the market. Delist",
  "mine.delistedOk": "Delisted",
  "mine.delistHint": "This skill is delisted: your copy stays, but it can no longer be updated from the market.",
  "common.save": "Save",
  "common.saving": "Saving…",
  "common.cancel": "Cancel",
  "skills.editDescription": "Description (frontmatter)",
  "skills.editBody": "Body (markdown)",
  "mine.edit": "Edit",
  "mine.editTitle": "Edit skill",
  "mine.updated": "Updated",
  "theme.light": "Light",
  "theme.dark": "Dark",
})
