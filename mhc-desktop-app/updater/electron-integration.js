"use strict";
/**
 * Electron-side glue for the updater. Owns the bootstrap, the
 * background loop, and the IPC handlers the renderer talks to.
 *
 * Kept out of main.ts so the diff stays small and so unit tests can
 * ignore it. main.ts only imports ``wireUpdater`` once.
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.wireUpdater = wireUpdater;
exports.wireUpdaterEarly = wireUpdaterEarly;
exports.getUpdater = getUpdater;
const electron_1 = require("electron");
const index_1 = require("./index");
const DEFAULT_MANIFEST_URL = process.env.MHC_MANIFEST_URL
    || "https://github.com/J0ey1iu/mhc-desktop/releases/latest/download/update.json";
// GH proxies tried in order if the primary URL fails. Sticky: once we
// pick a working one, we cache it in last-good.json's manifest_source
// so subsequent launches prefer it.
const MIRRORS = [
    "https://mirror.ghproxy.com",
    "https://gh-proxy.com",
    "https://npmmirror.com/mirrors/mhc-desktop",
];
let booted = null;
let mainWindowRef = null;
let backendReady = false;
/** Wire everything. Call once from main.ts after app.whenReady().
 *
 *  ``isReadyForCommit`` is the backend's /ready promise — once it
 *  resolves we mark the staged Tier 2/3 apply as "committed"
 *  (writes last-good.json). If the promise is replaced by an
 *  error/timeout, the caller triggers rollback. */
async function wireUpdater(opts) {
    if (!opts.enabled) {
        console.log("[updater] dev mode — updater disabled");
        return;
    }
    mainWindowRef = opts.mainWindow;
    const handle = booted?.handle;
    if (!handle) {
        console.error("[updater] wireUpdater called before wireUpdaterEarly");
        return;
    }
    // 2. Wire IPC so the renderer can ask for status / trigger checks.
    electron_1.ipcMain.handle("update:get-status", () => (0, index_1.snapshotForRenderer)(handle));
    electron_1.ipcMain.handle("update:check-now", async () => {
        await handle.checkNow();
        return (0, index_1.snapshotForRenderer)(handle);
    });
    electron_1.ipcMain.handle("update:install", async () => {
        await handle.installAvailable();
        return (0, index_1.snapshotForRenderer)(handle);
    });
    electron_1.ipcMain.handle("update:apply-now", async () => {
        const r = await handle.applyPending();
        return { applied: r.applied };
    });
    electron_1.ipcMain.handle("update:rollback", async () => {
        const r = await handle.rollbackNow();
        return { rolled: r.rolled };
    });
    // 3. Once the backend is ready and serving, mark the apply as
    //    committed. If the backend fails to come up (a bad apply broke
    //    server.py), call rollbackNow to restore.
    opts
        .isReadyForCommit()
        .then(async () => {
        backendReady = true;
        const i = handle.getInfo();
        if (i.state === "committed") {
            await handle.commitIfHealthy({
                versions: {
                    spa: i.available?.spa,
                    content_packs: i.available?.content_packs,
                    backend: i.available?.backend,
                },
            });
            sendToRenderer("update:state", (0, index_1.snapshotForRenderer)(handle));
        }
    })
        .catch(async (err) => {
        if (!backendReady) {
            console.error(`[updater] backend failed to come up; rolling back: ${err}`);
            const r = await handle.rollbackNow();
            console.log(`[updater] rolled back: ${r.rolled.join(", ") || "(nothing)"}`);
        }
    });
    // 4. Background loop. Initial check fires immediately; subsequent
    //    every prefs.checkIntervalMs (default 6h).
    handle.startBackgroundLoop();
}
/** Bootstrap phase: initialize prefs/last-good and apply any staged
 *  payloads BEFORE the backend starts. Called early in main.ts's
 *  bootstrap(). */
async function wireUpdaterEarly() {
    try {
        booted = await (0, index_1.bootstrapUpdater)({
            defaultManifestUrl: DEFAULT_MANIFEST_URL,
            mirrors: MIRRORS,
        });
    }
    catch (e) {
        console.error(`[updater] bootstrap failed: ${e.message}`);
        return;
    }
    const handle = booted.handle;
    // Forward state transitions to renderer (settings page listens).
    // sendToRenderer() is a no-op if mainWindowRef is null (early phase).
    handle.onStateChange((info) => {
        sendToRenderer("update:state", (0, index_1.snapshotForRenderer)(handle));
        if (info.state === "staged") {
            notifyStaged();
        }
        else if (info.state === "rolled_back") {
            notifyRolledBack(info.error);
        }
        else if (info.state === "update_available" && !info.forceTier1) {
            notifyAvailable(info);
        }
    });
    // Apply staged payloads BEFORE backend starts.
    if ((0, index_1.hasStagedManifest)(electron_1.app.getPath("userData"))) {
        console.log("[updater] staged update detected — applying before backend start");
        try {
            const r = await handle.applyPending();
            console.log(`[updater] applied: ${r.applied.join(", ")}`);
        }
        catch (e) {
            console.error(`[updater] apply failed at boot: ${e.message}`);
            // applyPending already handles internal rollback; we just log.
        }
    }
}
// ---------- helpers ----------
function sendToRenderer(channel, payload) {
    if (!mainWindowRef || mainWindowRef.isDestroyed())
        return;
    mainWindowRef.webContents.send(channel, payload);
}
function notifyAvailable(info) {
    const versions = Object.values(info.available ?? {}).filter(Boolean);
    if (versions.length === 0)
        return;
    new electron_1.Notification({
        title: "mhc-desktop 有新版本可用",
        body: `${versions.join(", ")} — 设置 → 关于 中点击“立即更新”`,
    }).show();
}
function notifyStaged() {
    new electron_1.Notification({
        title: "mhc-desktop 更新已下载",
        body: "下次启动时自动安装，或点击托盘立即重启。",
    }).show();
}
function notifyRolledBack(error) {
    new electron_1.Notification({
        title: "mhc-desktop 更新已回滚",
        body: error ? `原因: ${error}` : "新版本启动失败，已恢复到上一可用版本。",
    }).show();
}
/** Expose access for tests or for the rare in-session backend reload
 *  (Tier 3). Not used in MVP. */
function getUpdater() {
    return booted?.handle ?? null;
}
//# sourceMappingURL=electron-integration.js.map