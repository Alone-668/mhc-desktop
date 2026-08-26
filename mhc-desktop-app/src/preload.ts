/**
 * Minimal preload script — sets up a secure context bridge.
 *
 * The frontend uses fetch() for everything (which works through the
 * vite proxy in dev and direct localhost in production), so this
 * preload is intentionally tiny. Add API surfaces here as needed.
 */

import { contextBridge, ipcRenderer, webUtils } from "electron"

contextBridge.exposeInMainWorld("mhc", {
  versions: {
    electron: process.versions.electron,
    node: process.versions.node,
  },
  platform: process.platform,
  window: {
    minimize: () => ipcRenderer.invoke("window:minimize"),
    toggleMaximize: () => ipcRenderer.invoke("window:toggle-maximize"),
    close: () => ipcRenderer.invoke("window:close"),
    /** Force-quit the app, bypassing the close-to-tray prompt. Wired
     *  to the tray menu's "Quit" entry and to any UI button that
     *  means "really exit, no questions asked". */
    quit: () => ipcRenderer.invoke("window:quit") as Promise<void>,
    isMaximized: () => ipcRenderer.invoke("window:is-maximized") as Promise<boolean>,
    onMaximizeChange: (cb: (max: boolean) => void) => {
      const handler = (_e: unknown, max: boolean) => cb(max)
      ipcRenderer.on("window:maximize-changed", handler)
      return () => ipcRenderer.removeListener("window:maximize-changed", handler)
    },
  },
  // Skill import helpers — see main.ts for the IPC handlers.
  pickFolder: () => ipcRenderer.invoke("dialog:pick-folder") as Promise<string | null>,
  pickFile: (opts?: {
    filters?: { name: string; extensions: string[] }[]
  }) =>
    ipcRenderer.invoke("dialog:pick-file", opts ?? {}) as Promise<{
      path: string
      name: string
    } | null>,
  readFile: (p: string) =>
    ipcRenderer.invoke("fs:read-file", p) as Promise<ArrayBuffer | null>,
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
  getPathForFile: (file: File): string => {
    try {
      return webUtils.getPathForFile(file) || ""
    } catch {
      return ""
    }
  },
})
