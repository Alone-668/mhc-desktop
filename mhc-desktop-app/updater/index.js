"use strict";
/**
 * Public surface for the updater module. main.ts imports only from
 * here; everything else in the module is internal.
 *
 * The factory wires up the orchestrator against an Electron-shaped
 * context. Tests can drive the orchestrator directly via
 * ``createRollout`` (rollout.ts) — they don't go through this file.
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.hasStagedManifest = exports.DEFAULT_PREFS = void 0;
exports.bootstrapUpdater = bootstrapUpdater;
exports.snapshotForRenderer = snapshotForRenderer;
const electron_1 = require("electron");
const rollout_1 = require("./rollout");
async function bootstrapUpdater(deps) {
    const userDataPath = electron_1.app.getPath("userData");
    const resourcesPath = process.resourcesPath ?? "";
    if (!resourcesPath) {
        throw new Error("bootstrapUpdater called outside packaged build — dev mode skips updates");
    }
    const appVersion = electron_1.app.getVersion();
    const prefsFile = readPrefsFromElectronStore();
    const prefs = (0, rollout_1.mergePrefsFromFile)(prefsFile);
    let lastGood = await (0, rollout_1.readLastGood)(userDataPath);
    if (!lastGood) {
        await (0, rollout_1.writeEmptyLastGood)(userDataPath, appVersion);
        lastGood = await (0, rollout_1.readLastGood)(userDataPath);
    }
    const current = (0, rollout_1.currentVersionsFromLastGood)(appVersion, lastGood);
    const ctx = {
        resourcesPath,
        userDataPath,
        appVersion,
        current,
        prefs,
        mirrors: deps.mirrors,
        defaultManifestUrl: deps.defaultManifestUrl,
    };
    const handle = (0, rollout_1.createRollout)(ctx);
    return {
        handle,
        async applyPending() {
            const r = await handle.applyPending();
            return { applied: r.applied };
        },
    };
}
// electron-store is loaded lazily so dev mode (where the package may
// not be installed the same way) doesn't crash on import.
function readPrefsFromElectronStore() {
    try {
        // eslint-disable-next-line @typescript-eslint/no-var-requires
        const v = require("electron-store");
        const Store = v.default ?? v;
        const s = new Store({ name: "mhc-desktop-prefs" });
        const raw = s.get("updater");
        return { updater: raw };
    }
    catch {
        return {};
    }
}
var prefs_1 = require("./prefs");
Object.defineProperty(exports, "DEFAULT_PREFS", { enumerable: true, get: function () { return prefs_1.DEFAULT_PREFS; } });
var rollout_2 = require("./rollout");
Object.defineProperty(exports, "hasStagedManifest", { enumerable: true, get: function () { return rollout_2.hasStagedManifest; } });
/** Helper for the renderer: a small JSON snapshot of the current
 *  state suitable for shipping over IPC. */
function snapshotForRenderer(handle) {
    const i = handle.getInfo();
    return {
        state: i.state,
        releasedAt: i.releasedAt,
        available: i.available,
        error: i.error,
        progressBytes: i.progressBytes,
        progressTotal: i.progressTotal,
        channel: i.channel,
    };
}
//# sourceMappingURL=index.js.map