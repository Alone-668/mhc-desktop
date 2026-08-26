"use strict";
/**
 * Minimal preload script — sets up a secure context bridge.
 *
 * The frontend uses fetch() for everything (which works through the
 * vite proxy in dev and direct localhost in production), so this
 * preload is intentionally tiny. Add API surfaces here as needed.
 */
Object.defineProperty(exports, "__esModule", { value: true });
const electron_1 = require("electron");
electron_1.contextBridge.exposeInMainWorld("mhc", {
    versions: {
        electron: process.versions.electron,
        node: process.versions.node,
    },
    platform: process.platform,
    window: {
        minimize: () => electron_1.ipcRenderer.invoke("window:minimize"),
        toggleMaximize: () => electron_1.ipcRenderer.invoke("window:toggle-maximize"),
        close: () => electron_1.ipcRenderer.invoke("window:close"),
        /** Force-quit the app, bypassing the close-to-tray prompt. Wired
         *  to the tray menu's "Quit" entry and to any UI button that
         *  means "really exit, no questions asked". */
        quit: () => electron_1.ipcRenderer.invoke("window:quit"),
        isMaximized: () => electron_1.ipcRenderer.invoke("window:is-maximized"),
        onMaximizeChange: (cb) => {
            const handler = (_e, max) => cb(max);
            electron_1.ipcRenderer.on("window:maximize-changed", handler);
            return () => electron_1.ipcRenderer.removeListener("window:maximize-changed", handler);
        },
    },
    // Skill import helpers — see main.ts for the IPC handlers.
    pickFolder: () => electron_1.ipcRenderer.invoke("dialog:pick-folder"),
    pickFile: (opts) => electron_1.ipcRenderer.invoke("dialog:pick-file", opts ?? {}),
    readFile: (p) => electron_1.ipcRenderer.invoke("fs:read-file", p),
    /**
     * Resolve a File from <input type="file"> to its absolute path on
     * disk. Electron 32+ removed the synchronous ``File.path``
     * attribute for security (it leaked OS paths into the renderer
     * without an explicit user gesture). The replacement is
     * ``webUtils.getPathForFile(file)``, which must be called from a
     * trusted context — so we expose it through the preload bridge
     * and never expose the raw ``webUtils`` object to the page.
     *
     * Returns an empty string when the file has no resolvable path
     * (e.g. dropped from another renderer, or non-Chromium File
     * instance). The caller treats "" as "no path available" — the
     * backend's ``_format_files_block`` renders a name-only line in
     * that case so the model still sees the attachment exists.
     */
    getPathForFile: (file) => {
        try {
            return electron_1.webUtils.getPathForFile(file) || "";
        }
        catch {
            return "";
        }
    },
});
//# sourceMappingURL=preload.js.map