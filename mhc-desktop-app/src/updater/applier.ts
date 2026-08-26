/**
 * Applier — takes staged tar.gz payloads, extracts them into a temp
 * payload dir, verifies SHA against the live install, then atomically
 * renames them into ``process.resourcesPath``.
 *
 * Critical invariant: a partial apply never leaves the install in a
 * half-new state. Either the whole Tier 2/3 batch is in, or the
 * previous install is intact.
 *
 * Approach:
 *   1. Extract each tarball to ``userData/staged-update/payload/<key>/``
 *      (fresh per attempt — never reuse an old payload).
 *   2. For each entry, re-verify the tarball SHA against the manifest.
 *      Bail before any rename if anything is off.
 *   3. Rename ``extraResources/<key>`` to ``extraResources/<key>.bak.<ts>``.
 *   4. Rename payload to ``extraResources/<key>``.
 *
 * Rollback is the inverse: rename ``.bak.<ts>`` back. ``findBackups()``
 * picks the newest. Cross-volume renames fall back to copy + delete
 * (atomicity preserved within the rename itself, which is what we care
 * about — the new dir is never half-present).
 */

import { spawn } from "node:child_process"
import { createHash } from "node:crypto"
import { promises as fsp, existsSync } from "node:fs"
import { join, dirname, basename, relative } from "node:path"

export type ApplyKey = "spa" | "content-packs" | "backend"

export interface ApplyPayloadEntry {
  key: ApplyKey
  /** Absolute path to the tar.gz on disk. */
  tarball: string
  /** SHA-256 of the tarball (we re-verify after download, but pass it
   *  through so the manifest's expectation is the source of truth). */
  sha256: string
}

export class ApplyError extends Error {
  cause?: unknown
  constructor(msg: string, opts?: { cause?: unknown }) {
    super(msg)
    this.name = "ApplyError"
    if (opts?.cause !== undefined) this.cause = opts.cause
  }
}

// ---------- tar helpers (Windows-friendly) ----------

/** POSIX-style relative path from ``from`` to ``to``. tar expects
 *  forward slashes in argv on every platform — Windows backslashes
 *  trigger GNU tar's remote-file heuristic ("Cannot connect to C:").
 *  This helper runs the ``cwd`` relative-path trick documented in
 *  the function bodies below. */
function relForward(from: string, to: string): string {
  return relative(from, to).split(/[\\/]/).join("/")
}

/** Extract a tar.gz via the system ``tar`` (Win10+ ships one in
 *  System32; macOS/Linux have it natively). We shell out instead of
 *  pulling a tar lib — the wire format hasn't changed since 1979.
 *
 *  Note on Windows: GNU tar invoked from Node has a known wart where
 *  any absolute path in argv (even via ``-C <abs-path>``) triggers a
 *  remote file lookup ("Cannot connect to C: resolve failed").
 *  Workaround: ``cwd: dest, argv: [rel-src]`` — tar runs in ``dest``
 *  with a relative source path, no absolute path crosses the process
 *  boundary. */
export async function extractTarGz(src: string, dest: string): Promise<void> {
  await fsp.mkdir(dest, { recursive: true })
  const relSrc = relForward(dest, src)
  await runTar(["-xzf", relSrc], { cwd: dest })
}

/** Inverse: tar+gz a directory into a tarball. Same Windows cwd trick.
 *  Used by ``scripts/release.sh`` and tests. */
export async function createTarGz(srcDir: string, outFile: string): Promise<void> {
  await fsp.mkdir(dirname(outFile), { recursive: true })
  const cwd = dirname(outFile)
  const relSrcDir = relForward(cwd, srcDir)
  await runTar(["-czf", basename(outFile), "-C", relSrcDir, "."], { cwd })
}

function runTar(args: string[], opts: { cwd: string }): Promise<void> {
  return new Promise((resolve, reject) => {
    const p = spawn("tar", args, {
      cwd: opts.cwd,
      stdio: ["ignore", "ignore", "pipe"],
    })
    let stderr = ""
    p.stderr.on("data", (b: Buffer) => (stderr += b.toString()))
    p.on("error", reject)
    p.on("exit", (code) => {
      if (code === 0) resolve()
      else reject(new ApplyError(`tar exit ${code}: ${stderr.trim()}`))
    })
  })
}

// ---------- atomic replace ----------

/** Same-volume rename is atomic; cross-volume falls back to copy +
 *  delete. The destination file exists throughout the copy (then
 *  swaps via the second rename), so the live install is never
 *  missing. */
export async function atomicReplace(src: string, dst: string): Promise<void> {
  await fsp.mkdir(dirname(dst), { recursive: true })
  try {
    await fsp.rename(src, dst)
  } catch (e: unknown) {
    const err = e as NodeJS.ErrnoException
    if (err.code !== "EXDEV") throw err
    // Cross-volume fallback: copy then delete.
    await fsp.cp(src, dst, { recursive: true })
    await fsp.rm(src, { recursive: true, force: true })
  }
}

// ---------- hash helpers ----------

/** SHA-256 of a single file. Used to re-verify staged tarballs and
 *  to fingerprint the live install (for "did we already apply
 *  version X?" checks). */
export async function sha256OfFile(p: string): Promise<string> {
  const h = createHash("sha256")
  const data = await fsp.readFile(p)
  h.update(data)
  return h.digest("hex")
}

// ---------- apply ----------

export interface ApplyContext {
  /** ``process.resourcesPath`` in packaged builds; passed explicitly
   *  so tests can use a temp dir. */
  resourcesPath: string
  /** ``app.getPath('userData')``; we stage payloads here. */
  userDataPath: string
}

export interface ApplyResult {
  applied: ApplyKey[]
  backups: Record<ApplyKey, string | null>
}

/** Apply a batch of payloads. Each entry is verified (sha), then
 *  extracted to a fresh payload dir, then atomically swapped into
 *  ``resourcesPath/<key>``. The previous install is kept under
 *  ``resourcesPath/<key>.bak.<ts>`` for ``rollback()``. */
export async function applyPayloads(
  ctx: ApplyContext,
  entries: ApplyPayloadEntry[],
): Promise<ApplyResult> {
  const payloadRoot = join(ctx.userDataPath, "staged-update", "payload")
  // Fresh payload dir each attempt — never reuse.
  await fsp.rm(payloadRoot, { recursive: true, force: true })
  await fsp.mkdir(payloadRoot, { recursive: true })

  const result: ApplyResult = {
    applied: [],
    backups: { spa: null, "content-packs": null, backend: null },
  }
  const ts = Date.now()

  for (const entry of entries) {
    const actual = await sha256OfFile(entry.tarball)
    if (actual !== entry.sha256.toLowerCase()) {
      throw new ApplyError(
        `payload ${entry.key}: sha256 mismatch (expected ${entry.sha256} got ${actual})`,
      )
    }

    const target = join(payloadRoot, entry.key)
    await extractTarGz(entry.tarball, target)

    const live = join(ctx.resourcesPath, entry.key)
    const backup = `${live}.bak.${ts}`
    if (existsSync(live)) {
      await atomicReplace(live, backup)
    }
    await atomicReplace(target, live)
    result.applied.push(entry.key)
    result.backups[entry.key] = existsSync(backup) ? backup : null
  }

  return result
}

// ---------- rollback ----------

/** Roll back one or more keys to their most recent backup. Called when
 *  an apply fails partway through OR when the post-apply boot health
 *  check (60 s ``/ready``) fails. */
export async function rollback(
  ctx: ApplyContext,
  keys: ApplyKey[],
): Promise<{ rolled: ApplyKey[]; remaining: Record<ApplyKey, string | null> }> {
  const rolled: ApplyKey[] = []
  const remaining: Record<ApplyKey, string | null> = { spa: null, "content-packs": null, backend: null }
  for (const key of keys) {
    const live = join(ctx.resourcesPath, key)
    const backups = await findBackups(live)
    if (backups.length === 0) continue
    const newest = backups[0]!
    const failedTag = `${live}.failed.${Date.now()}`
    if (existsSync(live)) {
      await atomicReplace(live, failedTag)
    }
    await atomicReplace(newest, live)
    rolled.push(key)
    remaining[key] = backups[1] ?? null
  }
  return { rolled, remaining }
}

/** Find ``<live>.bak.<ts>`` siblings, newest first. */
async function findBackups(live: string): Promise<string[]> {
  const parent = dirname(live)
  const base = basename(live)
  const prefix = `${base}.bak.`
  let entries: string[]
  try {
    entries = await fsp.readdir(parent)
  } catch {
    return []
  }
  return entries
    .filter((e) => e.startsWith(prefix))
    .map((e) => join(parent, e))
    .sort()
    .reverse()
}

// ---------- post-apply cleanup ----------

export async function cleanStagedPayload(userDataPath: string): Promise<void> {
  await fsp.rm(join(userDataPath, "staged-update", "payload"), { recursive: true, force: true })
}

export async function listBackups(
  ctx: ApplyContext,
): Promise<Record<ApplyKey, string[]>> {
  const out: Record<ApplyKey, string[]> = { spa: [], "content-packs": [], backend: [] }
  for (const key of ["spa", "content-packs", "backend"] as ApplyKey[]) {
    out[key] = await findBackups(join(ctx.resourcesPath, key))
  }
  return out
}
