/**
 * Electron-side glue for the updater. Owns the bootstrap, the
 * background loop, and the IPC handlers the renderer talks to.
 */

import { app, BrowserWindow, ipcMain, Notification } from "electron"
import {
  bootstrapUpdater,
  hasStagedManifest,
  snapshotForRenderer,
  type UpdaterBootstrap,
} from "./index"

const DEFAULT_MANIFEST_URL =
  "https://github.com/J0ey1iu/mhc-desktop/releases/latest/download/update.json"

// GH proxies tried in order if the primary URL fails. Sticky: once we
// pick a working one, we cache it in last-good.json's manifest_source
// so subsequent launches prefer it.
const MIRRORS = [
  "https://mirror.ghproxy.com",
  "https://gh-proxy.com",
  "https://npmmirror.com/mirrors/mhc-desktop",
]

let booted: UpdaterBootstrap | null = null
let mainWindowRef: BrowserWindow | null = null

/** Wire everything. Call once from main.ts after app.whenReady().
 *
 *  ``isReadyForCommit`` is the backend's /ready promise — once it
 *  resolves we mark the staged Tier 2/3 apply as "committed"
 *  (writes last-good.json). If the promise is replaced by an
 *  error/timeout, the caller triggers rollback. */
export async function wireUpdater(opts: {
  mainWindow: BrowserWindow
  isReadyForCommit: () => Promise<void>
  /** When false (dev mode), skip everything — main.ts sets this when
   *  isPackaged is false. */
  enabled: boolean
}): Promise<void> {
  if (!opts.enabled) {
    console.log("[updater] dev mode — updater disabled")
    return
  }
  mainWindowRef = opts.mainWindow

  try {
    booted = await bootstrapUpdater({ defaultManifestUrl: DEFAULT_MANIFEST_URL, mirrors: MIRRORS })
  } catch (e) {
    console.error(`[updater] bootstrap failed: ${(e as Error).message}`)
    return
  }

  const handle = booted.handle
  // Forward state transitions to renderer; mainWindowRef is null in
  // early phase so calls are no-ops until the window exists.
  handle.onStateChange((info) => {
    sendToRenderer("update:state", snapshotForRenderer(handle))
    if (info.state === "staged") notifyStaged()
    else if (info.state === "rolled_back") notifyRolledBack(info.error)
    else if (info.state === "update_available" && !info.forceTier1) notifyAvailable(info)
  })

  // Apply staged payloads BEFORE the backend starts so the new SPA
  // and content-packs are what the user sees on launch.
  if (hasStagedManifest(app.getPath("userData"))) {
    console.log("[updater] staged update detected — applying before backend start")
    try {
      const r = await handle.applyPending()
      console.log(`[updater] applied: ${r.applied.join(", ")}`)
    } catch (e) {
      console.error(`[updater] apply failed at boot: ${(e as Error).message}`)
    }
  }

  ipcMain.handle("update:get-status", () => snapshotForRenderer(handle))
  ipcMain.handle("update:check-now", async () => {
    await handle.checkNow()
    return snapshotForRenderer(handle)
  })
  ipcMain.handle("update:install", async () => {
    await handle.installAvailable()
    return snapshotForRenderer(handle)
  })
  ipcMain.handle("update:apply-now", async () => {
    await handle.applyPending()
    return snapshotForRenderer(handle)
  })
  ipcMain.handle("update:rollback", async () => {
    const r = await handle.rollbackNow()
    return { rolled: r.rolled }
  })

  // Once the backend is ready and serving, mark the apply as
  // committed. If the backend fails to come up (a bad apply broke
  // server.py), call rollbackNow to restore.
  opts
    .isReadyForCommit()
    .then(async () => {
      const i = handle.getInfo()
      if (i.state === "committed") {
        await handle.commitIfHealthy({
          versions: {
            spa: i.available?.spa,
            content_packs: i.available?.content_packs,
            backend: i.available?.backend,
          },
        })
        sendToRenderer("update:state", snapshotForRenderer(handle))
      }
    })
    .catch(async (err) => {
      console.error(`[updater] backend failed to come up; rolling back: ${err}`)
      const r = await handle.rollbackNow()
      console.log(`[updater] rolled back: ${r.rolled.join(", ") || "(nothing)"}`)
    })

  handle.startBackgroundLoop()
}

// ---------- helpers ----------

function sendToRenderer(channel: string, payload: unknown): void {
  if (!mainWindowRef || mainWindowRef.isDestroyed()) return
  mainWindowRef.webContents.send(channel, payload)
}

function notifyAvailable(info: { available?: { spa?: string; content_packs?: string; backend?: string } }): void {
  const versions = Object.values(info.available ?? {}).filter(Boolean)
  if (versions.length === 0) return
  new Notification({
    title: "mhc-desktop 有新版本可用",
    body: `${versions.join(", ")} — 设置 → 关于 中点击“立即更新”`,
  }).show()
}

function notifyStaged(): void {
  new Notification({
    title: "mhc-desktop 更新已下载",
    body: "下次启动时自动安装，或点击托盘立即重启。",
  }).show()
}

function notifyRolledBack(error?: string): void {
  new Notification({
    title: "mhc-desktop 更新已回滚",
    body: error ? `原因: ${error}` : "新版本启动失败，已恢复到上一可用版本。",
  }).show()
}
