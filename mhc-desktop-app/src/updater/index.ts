/**
 * Public surface for the updater module. main.ts imports only from
 * here; everything else in the module is internal.
 */

import { app } from "electron"
import {
  createRollout,
  currentVersionsFromLastGood,
  hasStagedManifest,
  readLastGood,
  writeEmptyLastGood,
  type RolloutContext,
  type RolloutHandle,
  type UpdateInfo,
} from "./rollout"
import { readUpdaterPrefsFromFile, type UpdaterPrefs } from "./prefs"

export interface ElectronDeps {
  /** Manifest URL when prefs.manifestUrl is empty. */
  defaultManifestUrl: string
  /** Optional list of GH-proxy mirrors tried in order when the
   *  primary manifest fetch fails. */
  mirrors?: string[]
}

export interface UpdaterBootstrap {
  handle: RolloutHandle
}

export async function bootstrapUpdater(deps: ElectronDeps): Promise<UpdaterBootstrap> {
  const userDataPath = app.getPath("userData")
  const resourcesPath = (process as unknown as { resourcesPath?: string }).resourcesPath ?? ""
  if (!resourcesPath) {
    throw new Error("bootstrapUpdater called outside packaged build — dev mode skips updates")
  }
  const appVersion = app.getVersion()
  const prefs = readUpdaterPrefsFromFile(readPrefsFromElectronStore())
  let lastGood = await readLastGood(userDataPath)
  if (!lastGood) {
    await writeEmptyLastGood(userDataPath, appVersion)
    lastGood = await readLastGood(userDataPath)
  }
  const ctx: RolloutContext = {
    resourcesPath,
    userDataPath,
    appVersion,
    current: currentVersionsFromLastGood(appVersion, lastGood),
    prefs,
    mirrors: deps.mirrors,
    defaultManifestUrl: deps.defaultManifestUrl,
  }
  return { handle: createRollout(ctx) }
}

// electron-store is loaded lazily so dev mode (where the package may
// not be installed the same way) doesn't crash on import.
function readPrefsFromElectronStore(): { updater?: Partial<UpdaterPrefs> } {
  try {
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const v = require("electron-store")
    const Store = v.default ?? v
    const s = new Store({ name: "mhc-desktop-prefs" })
    return { updater: s.get("updater") as Partial<UpdaterPrefs> | undefined }
  } catch {
    return {}
  }
}

/** Snapshot for the renderer. ``forceTier1`` is internal — strip it
 *  before crossing the IPC boundary. */
export function snapshotForRenderer(handle: RolloutHandle): Omit<UpdateInfo, "forceTier1"> {
  const { forceTier1: _, ...rest } = handle.getInfo()
  return rest
}

export type { RolloutHandle, UpdateInfo, UpdateState } from "./rollout"
export { DEFAULT_PREFS } from "./prefs"
export { hasStagedManifest } from "./rollout"
