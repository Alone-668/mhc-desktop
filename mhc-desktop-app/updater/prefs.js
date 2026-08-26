"use strict";
/**
 * Updater preferences wrapper. Reuses the existing
 * ``mhc-desktop-prefs.json`` electron-store file so the user has
 * one config, not three.
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.STAGED_MANIFEST_FILENAME = exports.STAGED_DIR = exports.LAST_GOOD_FILENAME = exports.DEFAULT_PREFS = void 0;
exports.readUpdaterPrefsFromFile = readUpdaterPrefsFromFile;
exports.makeLastGood = makeLastGood;
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
function makeLastGood(versions) {
    return { ...versions, updated_at: new Date().toISOString() };
}
//# sourceMappingURL=prefs.js.map