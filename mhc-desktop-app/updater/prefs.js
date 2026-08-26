"use strict";
/**
 * Updater preferences wrapper. Reuses the existing
 * ``mhc-desktop-prefs.json`` electron-store file so the user has
 * one config, not three. Prefs field schema is versioned so we can
 * add fields without breaking older clients.
 *
 * All getters return defaults when the field is absent — so adding
 * a new pref is safe to deploy before the UI exposes it.
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.STAGED_MANIFEST_FILENAME = exports.STAGED_DIR = exports.LAST_GOOD_FILENAME = exports.DEFAULT_PREFS = void 0;
exports.readUpdaterPrefsFromFile = readUpdaterPrefsFromFile;
exports.makeLastGood = makeLastGood;
exports.emptyLastGood = emptyLastGood;
exports.DEFAULT_PREFS = {
    manifestUrl: "",
    channel: "stable",
    autoUpdate: true,
    checkIntervalMs: 6 * 60 * 60 * 1000, // 6 h
};
exports.LAST_GOOD_FILENAME = "last-good.json";
exports.STAGED_DIR = "staged-update";
exports.STAGED_MANIFEST_FILENAME = "manifest.json";
function readUpdaterPrefsFromFile(file) {
    const u = file.updater ?? {};
    return {
        manifestUrl: typeof u.manifestUrl === "string" ? u.manifestUrl : exports.DEFAULT_PREFS.manifestUrl,
        channel: u.channel === "beta" ? "beta" : exports.DEFAULT_PREFS.channel,
        autoUpdate: typeof u.autoUpdate === "boolean" ? u.autoUpdate : exports.DEFAULT_PREFS.autoUpdate,
        checkIntervalMs: typeof u.checkIntervalMs === "number" && u.checkIntervalMs > 0
            ? u.checkIntervalMs
            : exports.DEFAULT_PREFS.checkIntervalMs,
    };
}
/** Helpers for last-good.json — kept tiny because the on-disk file is
 *  read by hand from rollbacks. */
function makeLastGood(versions) {
    return { ...versions, updated_at: new Date().toISOString() };
}
function emptyLastGood(appVersion) {
    return { app: appVersion, updated_at: new Date().toISOString() };
}
//# sourceMappingURL=prefs.js.map