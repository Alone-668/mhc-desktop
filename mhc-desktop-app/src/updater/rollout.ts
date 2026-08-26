/**
 * Rollout orchestrator — wires manifest fetch, download, apply into
 * a single state machine the rest of the app subscribes to.
 *
 * See ``docs/UPDATE-MECHANISM.md`` §4 for the canonical state diagram.
 */

import { EventEmitter } from "node:events"
import { promises as fsp, existsSync } from "node:fs"
import { join } from "node:path"
import {
  diffManifest,
  fetchManifestWithMirrors,
  ManifestError,
  parseManifest,
  type AvailableUpdates,
  type CurrentVersions,
  type Manifest,
  type Tier2Entry,
  type Tier3Entry,
} from "./manifest"
import { downloadToFile, DownloadError } from "./downloader"
import {
  applyPayloads,
  cleanStagedPayload,
  rollback as rollbackPayloads,
  type ApplyContext,
  type ApplyKey,
} from "./applier"
import { createUpdaterLogger, type UpdaterLogger } from "./log"
import {
  DEFAULT_PREFS,
  LAST_GOOD_FILENAME,
  STAGED_DIR,
  STAGED_MANIFEST_FILENAME,
  makeLastGood,
  readUpdaterPrefsFromFile,
  type LastGoodVersions,
  type UpdaterPrefs,
} from "./prefs"

/** Snapshot of orchestrator state. Mirrored to the renderer via
 *  preload for display in Settings → Updates. */
export interface UpdateInfo {
  state: UpdateState
  releasedAt?: string
  available?: { spa?: string; content_packs?: string; backend?: string }
  error?: string
  progressBytes?: number
  progressTotal?: number
  forceTier1?: boolean
  channel?: "stable" | "beta"
}

export type UpdateState =
  | "idle"
  | "checking"
  | "update_available"
  | "downloading"
  | "download_failed"
  | "staged"
  | "applying"
  | "committed"
  | "rolled_back"

export interface RolloutContext extends ApplyContext {
  appVersion: string
  current: CurrentVersions
  /** Override the default check interval (ms). */
  checkIntervalMs?: number
  prefs: UpdaterPrefs
  defaultManifestUrl: string
  /** Mirrors tried in order when the primary manifest URL fails. */
  mirrors?: string[]
}

export interface RolloutDeps {
  logger?: UpdaterLogger
  /** Called on every state transition. */
  onState?: (info: UpdateInfo) => void
}

export interface RolloutHandle {
  startBackgroundLoop(): void
  checkNow(): Promise<UpdateInfo>
  installAvailable(): Promise<UpdateInfo>
  stageAvailable(updates?: AvailableUpdates): Promise<UpdateInfo>
  applyPending(): Promise<{ applied: ApplyKey[] }>
  commitIfHealthy(info: {
    versions: { spa?: string; content_packs?: string; backend?: string }
  }): Promise<void>
  rollbackNow(): Promise<{ rolled: ApplyKey[] }>
  getInfo(): UpdateInfo
  onStateChange(cb: (info: UpdateInfo) => void): () => void
  setPrefs(p: Partial<UpdaterPrefs>): Promise<void>
  getLastManifest(): Manifest | null
  dispose(): void
}

class Rollout {
  private ctx: RolloutContext
  private logger: UpdaterLogger
  private onState?: (info: UpdateInfo) => void
  private info: UpdateInfo = { state: "idle" }
  private lastManifest: Manifest | null = null
  private checkTimer: NodeJS.Timeout | null = null
  private running = false
  private emitter = new EventEmitter()

  constructor(ctx: RolloutContext, deps: RolloutDeps = {}) {
    this.ctx = ctx
    this.logger = deps.logger ?? createUpdaterLogger(ctx.userDataPath)
    this.onState = deps.onState
  }

  // ---------- public API ----------

  getInfo(): UpdateInfo { return this.info }
  getLastManifest(): Manifest | null { return this.lastManifest }

  onStateChange(cb: (info: UpdateInfo) => void): () => void {
    this.emitter.on("state", cb)
    return () => this.emitter.off("state", cb)
  }

  setPrefs(p: Partial<UpdaterPrefs>): Promise<void> {
    this.ctx.prefs = { ...this.ctx.prefs, ...p }
    return Promise.resolve()
  }

  startBackgroundLoop(): void {
    if (this.running) return
    this.running = true
    void this.checkNow().catch((e) => this.logger.error(`initial check failed: ${(e as Error).message}`))
    const ms = this.ctx.checkIntervalMs ?? this.ctx.prefs.checkIntervalMs
    this.checkTimer = setInterval(() => {
      void this.checkNow().catch((e) => this.logger.error(`scheduled check failed: ${(e as Error).message}`))
    }, ms)
  }

  async checkNow(): Promise<UpdateInfo> {
    if (!this.ctx.prefs.autoUpdate) {
      this.logger.info("autoUpdate disabled — skipping check")
      return this.info
    }
    this.setInfo({ ...this.info, state: "checking" })
    try {
      const { manifest, source } = await fetchManifestWithMirrors(
        this.manifestUrl(),
        this.ctx.mirrors ?? [],
        { timeoutMs: 8000 },
      )
      this.lastManifest = manifest
      this.logger.info(
        `manifest fetched from ${source} (released_at=${manifest.released_at}, channel=${manifest.channel})`,
      )
      const available = diffManifest(manifest, this.ctx.current)
      if (available.forceTier1) {
        this.logger.warn(`app ${this.ctx.appVersion} < min ${manifest.min_app_version} — Tier 1 required`)
        return this.setInfo({
          ...this.info,
          state: "update_available",
          releasedAt: manifest.released_at,
          available: {},
          forceTier1: true,
          channel: manifest.channel,
        })
      }
      const hasAny = available.spa || available.content_packs || available.backend
      if (!hasAny) {
        this.logger.info("no updates available")
        return this.setInfo({
          ...this.info,
          state: "idle",
          releasedAt: manifest.released_at,
          channel: manifest.channel,
        })
      }
      this.logger.info(
        `updates available: ${Object.keys(available).filter((k) => k !== "forceTier1").join(", ")}`,
      )
      return this.setInfo({
        ...this.info,
        state: "update_available",
        releasedAt: manifest.released_at,
        available: {
          spa: available.spa?.version,
          content_packs: available.content_packs?.version,
          backend: available.backend?.version,
        },
        channel: manifest.channel,
      })
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      this.logger.warn(`check failed: ${msg}`)
      return this.setInfo({ ...this.info, state: "download_failed", error: msg })
    }
  }

  async stageAvailable(updates?: AvailableUpdates): Promise<UpdateInfo> {
    if (!this.lastManifest) throw new Error("stageAvailable called before checkNow")
    const u = updates ?? diffManifest(this.lastManifest, this.ctx.current)
    if (!u.spa && !u.content_packs && !u.backend) {
      this.logger.info("stageAvailable: nothing to download")
      return this.info
    }
    if (!this.ctx.prefs.autoUpdate) {
      this.logger.info("autoUpdate disabled — refusing to stage")
      return this.setInfo({ ...this.info, state: "idle", error: "auto-update disabled" })
    }
    this.setInfo({ ...this.info, state: "downloading" })
    const staged = await this.downloadAll(u)
    const stagedDir = join(this.ctx.userDataPath, STAGED_DIR)
    await fsp.mkdir(stagedDir, { recursive: true })
    await fsp.writeFile(
      join(stagedDir, STAGED_MANIFEST_FILENAME),
      JSON.stringify(this.lastManifest, null, 2),
      "utf8",
    )
    this.logger.info(`staged: ${staged.join(", ")}`)
    return this.setInfo({
      ...this.info,
      state: "staged",
      releasedAt: this.lastManifest.released_at,
      available: {
        spa: u.spa?.version ?? this.info.available?.spa,
        content_packs: u.content_packs?.version ?? this.info.available?.content_packs,
        backend: u.backend?.version ?? this.info.available?.backend,
      },
      channel: this.lastManifest.channel,
    })
  }

  installAvailable(): Promise<UpdateInfo> {
    return this.stageAvailable()
  }

  async applyPending(): Promise<{ applied: ApplyKey[] }> {
    if (!existsSync(this.stagedManifestPath())) {
      this.logger.info("applyPending: no staged manifest — nothing to do")
      return { applied: [] }
    }
    // First-call path (no manifest in memory yet): re-read from disk.
    if (!this.lastManifest) await this.reloadStagedManifest()
    this.setInfo({ ...this.info, state: "applying" })
    const entries = this.collectStagedEntries()
    if (entries.length === 0) {
      this.logger.warn("applyPending: staged manifest had no recognized payloads")
      this.setInfo({ ...this.info, state: "committed" })
      await cleanStagedPayload(this.ctx.userDataPath)
      return { applied: [] }
    }
    try {
      const res = await applyPayloads(
        { resourcesPath: this.ctx.resourcesPath, userDataPath: this.ctx.userDataPath },
        entries,
      )
      this.logger.info(
        `applied: ${res.applied.join(", ")}; backups: ${Object.entries(res.backups)
          .filter(([, v]) => v).map(([k]) => k).join(", ")}`,
      )
      const appliedVersions = this.appliedVersionsFrom(res.applied)
      // Update ctx.current so a follow-up checkNow doesn't immediately
      // re-flag the just-installed version as available again. Cleanup
      // of staged payload happens in commitIfHealthy (post /ready).
      this.ctx.current = {
        app: this.ctx.appVersion,
        spa: appliedVersions.spa ?? this.ctx.current.spa,
        content_packs: appliedVersions["content-packs"] ?? this.ctx.current.content_packs,
        backend: appliedVersions.backend ?? this.ctx.current.backend,
      }
      this.setInfo({ ...this.info, state: "committed", available: appliedVersions })
      return { applied: res.applied }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      this.logger.error(`apply failed: ${msg}`)
      const { rolled } = await rollbackPayloads(
        { resourcesPath: this.ctx.resourcesPath, userDataPath: this.ctx.userDataPath },
        entries.map((e) => e.key),
      )
      this.setInfo({ ...this.info, state: "rolled_back", error: msg })
      this.logger.warn(`rolled back: ${rolled.join(", ")}`)
      return { applied: [] }
    }
  }

  async commitIfHealthy(info: {
    versions: { spa?: string; content_packs?: string; backend?: string }
  }): Promise<void> {
    if (this.info.state !== "committed") return
    const lg = makeLastGood({
      app: this.ctx.appVersion,
      spa: info.versions.spa ?? this.ctx.current.spa,
      content_packs: info.versions.content_packs ?? this.ctx.current.content_packs,
      backend: info.versions.backend ?? this.ctx.current.backend,
    })
    await fsp.writeFile(
      join(this.ctx.userDataPath, LAST_GOOD_FILENAME),
      JSON.stringify(lg, null, 2),
      "utf8",
    )
    this.ctx.current = {
      app: this.ctx.appVersion,
      spa: lg.spa,
      content_packs: lg.content_packs,
      backend: lg.backend,
    }
    await cleanStagedPayload(this.ctx.userDataPath)
    this.logger.info(`committed last-good: ${JSON.stringify(info.versions)}`)
    this.setInfo({ ...this.info, state: "idle" })
  }

  async rollbackNow(): Promise<{ rolled: ApplyKey[] }> {
    if (!this.lastManifest) await this.reloadStagedManifest()
    const entries = this.collectStagedEntries()
    if (entries.length === 0) {
      this.logger.warn("rollbackNow: nothing staged to roll back")
      return { rolled: [] }
    }
    const { rolled } = await rollbackPayloads(
      { resourcesPath: this.ctx.resourcesPath, userDataPath: this.ctx.userDataPath },
      entries.map((e) => e.key),
    )
    await cleanStagedPayload(this.ctx.userDataPath)
    this.setInfo({ ...this.info, state: "rolled_back", error: "manual rollback" })
    return { rolled }
  }

  dispose(): void {
    if (this.checkTimer) clearInterval(this.checkTimer)
    this.checkTimer = null
    this.running = false
  }

  // ---------- internals ----------

  private manifestUrl(): string {
    return this.ctx.prefs.manifestUrl || this.ctx.defaultManifestUrl
  }

  private stagedManifestPath(): string {
    return join(this.ctx.userDataPath, STAGED_DIR, STAGED_MANIFEST_FILENAME)
  }

  /** Re-read the staged manifest from disk and stash it as lastManifest.
   *  Returns silently on corruption — the caller's collectStagedEntries
   *  will then produce an empty list and apply becomes a no-op. */
  private async reloadStagedManifest(): Promise<void> {
    try {
      this.lastManifest = parseManifest(JSON.parse(await fsp.readFile(this.stagedManifestPath(), "utf8")))
    } catch {
      this.lastManifest = null
    }
  }

  private collectStagedEntries(): { key: ApplyKey; tarball: string; sha256: string }[] {
    const dir = join(this.ctx.userDataPath, STAGED_DIR)
    const entries: { key: ApplyKey; tarball: string; sha256: string }[] = []
    const t2 = this.lastManifest?.tier2
    const t3 = this.lastManifest?.tier3
    if (t2?.spa && existsSync(join(dir, "spa.tar.gz"))) {
      entries.push({ key: "spa", tarball: join(dir, "spa.tar.gz"), sha256: t2.spa.sha256 })
    }
    if (t2?.content_packs && existsSync(join(dir, "content-packs.tar.gz"))) {
      entries.push({
        key: "content-packs",
        tarball: join(dir, "content-packs.tar.gz"),
        sha256: t2.content_packs.sha256,
      })
    }
    if (t3?.backend && existsSync(join(dir, "backend.tar.gz"))) {
      entries.push({ key: "backend", tarball: join(dir, "backend.tar.gz"), sha256: t3.backend.sha256 })
    }
    return entries
  }

  private appliedVersionsFrom(applied: ApplyKey[]): { spa?: string; "content-packs"?: string; backend?: string } {
    const t2 = this.lastManifest?.tier2
    const t3 = this.lastManifest?.tier3
    const v: { spa?: string; "content-packs"?: string; backend?: string } = {}
    if (applied.includes("spa") && t2?.spa) v.spa = t2.spa.version
    if (applied.includes("content-packs") && t2?.content_packs) v["content-packs"] = t2.content_packs.version
    if (applied.includes("backend") && t3?.backend) v.backend = t3.backend.version
    return v
  }

  private async downloadAll(u: AvailableUpdates): Promise<string[]> {
    const stagedDir = join(this.ctx.userDataPath, STAGED_DIR)
    await fsp.mkdir(stagedDir, { recursive: true })
    const staged: string[] = []
    for (const [key, entry] of [
      ["spa", u.spa],
      ["content-packs", u.content_packs],
      ["backend", u.backend],
    ] as [ApplyKey, Tier2Entry | Tier3Entry | undefined][]) {
      if (!entry) continue
      await this.downloadOne(entry, join(stagedDir, `${key}.tar.gz`), key)
      staged.push(key)
    }
    return staged
  }

  private async downloadOne(entry: Tier2Entry | Tier3Entry, dest: string, label: string): Promise<void> {
    this.logger.info(`download start: ${label} ${entry.url} (${entry.size} bytes)`)
    try {
      const { bytes } = await downloadToFile(entry.url, dest, {
        expectedSha256: entry.sha256,
        contentLength: entry.size,
        onProgress: (n) => this.setInfo({ ...this.info, progressBytes: n, progressTotal: entry.size }),
      })
      this.logger.info(`download done: ${label} ${bytes} bytes`)
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      this.logger.error(`download failed: ${label} ${msg}`)
      this.setInfo({ ...this.info, state: "download_failed", error: `${label}: ${msg}` })
      throw e
    }
  }

  private setInfo(next: UpdateInfo): UpdateInfo {
    this.info = next
    this.logger.info(`state=${next.state}` + (next.error ? ` error=${next.error}` : ""))
    this.onState?.(next)
    this.emitter.emit("state", next)
    return next
  }
}

export function createRollout(ctx: RolloutContext, deps: RolloutDeps = {}): RolloutHandle {
  return new Rollout(ctx, deps) as unknown as RolloutHandle
}

// ---------- helpers exported for main.ts / index.ts ----------

export async function readLastGood(userDataPath: string): Promise<LastGoodVersions | null> {
  try {
    return JSON.parse(await fsp.readFile(join(userDataPath, LAST_GOOD_FILENAME), "utf8"))
  } catch {
    return null
  }
}

export function currentVersionsFromLastGood(
  appVersion: string,
  lastGood: LastGoodVersions | null,
): CurrentVersions {
  if (!lastGood) return { app: appVersion }
  return {
    app: lastGood.app ?? appVersion,
    spa: lastGood.spa,
    content_packs: lastGood.content_packs,
    backend: lastGood.backend,
  }
}

export async function writeEmptyLastGood(userDataPath: string, appVersion: string): Promise<void> {
  const lg: LastGoodVersions = makeLastGood({ app: appVersion })
  await fsp.writeFile(
    join(userDataPath, LAST_GOOD_FILENAME),
    JSON.stringify(lg, null, 2),
    "utf8",
  )
}

export function hasStagedManifest(userDataPath: string): boolean {
  return existsSync(join(userDataPath, STAGED_DIR, STAGED_MANIFEST_FILENAME))
}

export { ManifestError, DownloadError, DEFAULT_PREFS }
