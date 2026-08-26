/**
 * Updater preferences wrapper. Reuses the existing
 * ``mhc-desktop-prefs.json`` electron-store file so the user has
 * one config, not three.
 */

import type { UpdateChannel } from "./manifest"

export interface UpdaterPrefs {
  /** Override the manifest URL. Empty = use built-in default. */
  manifestUrl: string
  channel: UpdateChannel
  /** Master switch: false = check + log only, never download. */
  autoUpdate: boolean
  checkIntervalMs: number
}

export const DEFAULT_PREFS: UpdaterPrefs = {
  manifestUrl: "",
  channel: "stable",
  autoUpdate: true,
  checkIntervalMs: 6 * 60 * 60 * 1000, // 6 h
}

export interface LastGoodVersions {
  app: string
  spa?: string
  content_packs?: string
  backend?: string
  updated_at: string
}

export const LAST_GOOD_FILENAME = "last-good.json"
export const STAGED_DIR = "staged-update"
export const STAGED_MANIFEST_FILENAME = "manifest.json"

/** Prefs file may carry other keys (theme, locale, etc.); we only read
 *  the namespaced ``updater`` block. */
export interface PrefsFileShape {
  updater?: Partial<UpdaterPrefs>
}

export function readUpdaterPrefsFromFile(file: PrefsFileShape): UpdaterPrefs {
  const u = file.updater ?? {}
  return {
    manifestUrl: typeof u.manifestUrl === "string" ? u.manifestUrl : DEFAULT_PREFS.manifestUrl,
    channel: u.channel === "beta" ? "beta" : DEFAULT_PREFS.channel,
    autoUpdate: typeof u.autoUpdate === "boolean" ? u.autoUpdate : DEFAULT_PREFS.autoUpdate,
    checkIntervalMs:
      typeof u.checkIntervalMs === "number" && u.checkIntervalMs > 0
        ? u.checkIntervalMs
        : DEFAULT_PREFS.checkIntervalMs,
  }
}

export function makeLastGood(versions: Omit<LastGoodVersions, "updated_at">): LastGoodVersions {
  return { ...versions, updated_at: new Date().toISOString() }
}
