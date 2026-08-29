// 市场同步的共享状态 + 轮询（应用级单例）。
// 轮询在 App.vue 挂载时启动：每 45s 拉一次同步计划，无冲突的
// push/pull 自动执行；冲突才提醒用户决策。集合级 sha（local/remote
// set_sha）用于一眼判断整套是否一致。
import { computed, ref } from "vue"
import { api, type SyncPlan, type SyncResult } from "../api/client"
import { useSkillsStore } from "../stores/skills"

export const syncPlan = ref<SyncPlan | null>(null)
export const reminder = ref<SyncPlan | null>(null)
export const conflictSlugs = ref<string[]>([])
export const syncing = ref(false)
export const resolving = ref<string | null>(null)
export const lastCheckAt = ref(0)

export const reminderIssues = computed(() =>
  reminder.value ? reminder.value.conflicts.length : 0,
)

// Cloud copy slug → market entry author (from the sync manifest).
// The desktop shows it on local skill cards as "作者".
export const skillAuthors = computed(() => syncPlan.value?.authors ?? {})

// Cloud copy slug → matched market key + delisted flag (drives the
// "only my published skills can be delisted" button).
export const skillMarketKeys = computed(() => syncPlan.value?.market_slugs ?? {})
export const delistedSlugs = computed(() => {
  const m = new Set<string>()
  for (const [slug, delisted] of Object.entries(syncPlan.value?.delisted ?? {})) {
    if (delisted) m.add(slug)
  }
  return m
})

function issueCount(plan: SyncPlan): number {
  return Object.values(plan.actions).filter((a) => a.action !== "up-to-date").length
}

export async function refreshSync(): Promise<void> {
  try {
    syncPlan.value = await api.syncPlan()
    lastCheckAt.value = Math.floor(Date.now() / 1000)
  } catch (e) {
    // 市场未配置/不可达：静默，面板按需重试
    void e
  }
}

async function checkAndAct() {
  try {
    const plan = await api.syncPlan()
    syncPlan.value = plan
    lastCheckAt.value = Math.floor(Date.now() / 1000)

    const actions = Object.values(plan.actions)
    const auto = actions.filter((a) => a.action === "push" || a.action === "pull")
    const conflicts = plan.conflicts

    // 无冲突的 push/pull → 静默自动执行；冲突留给用户决策。
    if (auto.length > 0 && conflicts.length === 0) {
      await execute()
      return
    }

    if (conflicts.length > 0) {
      conflictSlugs.value = conflicts
      const sig = `${issueCount(plan)}:${Object.keys(plan.actions).sort().join(",")}`
      if (sessionStorage.getItem("mhc.sync.reminded") !== sig) {
        sessionStorage.setItem("mhc.sync.reminded", sig)
        reminder.value = plan
      }
    } else {
      reminder.value = null
      conflictSlugs.value = []
    }
  } catch {
    /* 市场不可达：静默，下轮重试 */
  }
}

export async function execute(): Promise<SyncResult | null> {
  syncing.value = true
  try {
    const res = await api.syncExecute()
    conflictSlugs.value = res.conflicts
    const store = useSkillsStore()
    await store.refresh()
    await refreshSync()
    return res
  } catch (e) {
    // 静默失败；面板/提醒会再试
    void e
    return null
  } finally {
    syncing.value = false
  }
}

export async function runSync(): Promise<void> {
  reminder.value = null
  await execute()
}

export async function resolveConflict(slug: string, choice: "local" | "remote"): Promise<void> {
  resolving.value = slug
  try {
    await api.resolveConflict(slug, choice)
    conflictSlugs.value = conflictSlugs.value.filter((s) => s !== slug)
    const store = useSkillsStore()
    await Promise.all([refreshSync(), store.refresh()])
  } finally {
    resolving.value = null
  }
}

let timer: ReturnType<typeof setInterval> | null = null

export function startSyncPolling(intervalMs = 45_000): void {
  if (timer) return
  void refreshSync()
  void checkAndAct()
  timer = setInterval(checkAndAct, intervalMs)
}

export function stopSyncPolling(): void {
  if (timer) { clearInterval(timer); timer = null }
}
