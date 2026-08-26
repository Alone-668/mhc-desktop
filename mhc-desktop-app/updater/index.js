"use strict";
/**
 * Public surface for the updater module. main.ts imports only from
 * here; everything else in the module is internal.
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.hasStagedManifest = exports.DEFAULT_PREFS = void 0;
exports.bootstrapUpdater = bootstrapUpdater;
exports.snapshotForRenderer = snapshotForRenderer;
const electron_1 = require("electron");
const rollout_1 = require("./rollout");
const prefs_1 = require("./prefs");
async function bootstrapUpdater(deps) {
    const userDataPath = electron_1.app.getPath("userData");
    const resourcesPath = process.resourcesPath ?? "";
    if (!resourcesPath) {
        throw new Error("bootstrapUpdater called outside packaged build — dev mode skips updates");
    }
    const appVersion = electron_1.app.getVersion();
    const prefs = (0, prefs_1.readUpdaterPrefsFromFile)(readPrefsFromElectronStore());
    let lastGood = await (0, rollout_1.readLastGood)(userDataPath);
    if (!lastGood) {
        await (0, rollout_1.writeEmptyLastGood)(userDataPath, appVersion);
        lastGood = await (0, rollout_1.readLastGood)(userDataPath);
    }
    const ctx = {
        resourcesPath,
        userDataPath,
        appVersion,
        current: (0, rollout_1.currentVersionsFromLastGood)(appVersion, lastGood),
        prefs,
        mirrors: deps.mirrors,
        defaultManifestUrl: deps.defaultManifestUrl,
    };
    return { handle: (0, rollout_1.createRollout)(ctx) };
}
// electron-store is loaded lazily so dev mode (where the package may
// not be installed the same way) doesn't crash on import.
function readPrefsFromElectronStore() {
    try {
        // eslint-disable-next-line @typescript-eslint/no-var-requires
        const v = require("electron-store");
        const Store = v.default ?? v;
        const s = new Store({ name: "mhc-desktop-prefs" });
        return { updater: s.get("updater") };
    }
    catch {
        return {};
    }
}
/** Snapshot for the renderer. ``forceTier1`` is internal — strip it
 *  before crossing the IPC boundary. */
function snapshotForRenderer(handle) {
    const { forceTier1: _, ...rest } = handle.getInfo();
    return rest;
}
var prefs_2 = require("./prefs");
Object.defineProperty(exports, "DEFAULT_PREFS", { enumerable: true, get: function () { return prefs_2.DEFAULT_PREFS; } });
var rollout_2 = require("./rollout");
Object.defineProperty(exports, "hasStagedManifest", { enumerable: true, get: function () { return rollout_2.hasStagedManifest; } });
//# sourceMappingURL=index.js.map