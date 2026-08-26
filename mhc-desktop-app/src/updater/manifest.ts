/**
 * Manifest types + fetch + validation.
 *
 * Pure logic, no Electron deps — tests run under plain `node --test`.
 *
 * Manifest shape lives in `docs/UPDATE-MECHANISM.md` §3. Anything we
 * change here must also update that doc; the manifest is the public
 * contract between the release pipeline and every installed client.
 */

export type UpdateChannel = "stable" | "beta"

export interface Tier2Entry {
  version: string
  url: string
  sha256: string
  size: number
}

export interface Tier3Entry extends Tier2Entry {
  /** PBS release tag, e.g. "20250814-x86_64-pc-windows-msvc-shared-install_only". */
  python_tag?: string
}

export interface Manifest {
  manifest_version: 1
  channel: UpdateChannel
  released_at: string
  tier2?: {
    spa?: Tier2Entry
    content_packs?: Tier2Entry
  }
  tier3?: {
    backend?: Tier3Entry
  }
  release_notes?: string
  /** Lower bound: clients older than this MUST go through Tier 1 first. */
  min_app_version: string
}

// ---------- validation ----------

export class ManifestError extends Error {
  cause?: unknown
  constructor(msg: string, opts?: { cause?: unknown }) {
    super(msg)
    this.name = "ManifestError"
    if (opts?.cause !== undefined) this.cause = opts.cause
  }
}

export function parseManifest(raw: unknown): Manifest {
  if (!raw || typeof raw !== "object") throw new ManifestError("manifest: not an object")
  const m = raw as Record<string, unknown>
  if (m.manifest_version !== 1) {
    throw new ManifestError(`manifest: unsupported manifest_version=${String(m.manifest_version)}`)
  }
  if (m.channel !== "stable" && m.channel !== "beta") {
    throw new ManifestError(`manifest: invalid channel=${String(m.channel)}`)
  }
  if (typeof m.released_at !== "string") throw new ManifestError("manifest: missing released_at")
  if (typeof m.min_app_version !== "string") throw new ManifestError("manifest: missing min_app_version")
  // Tier 2/3 entries are independently optional but if present must
  // be fully specified — partial entries leave the client unsure
  // whether to skip or fail.
  const t2 = m.tier2 as Record<string, unknown> | undefined
  const t3 = m.tier3 as Record<string, unknown> | undefined
  if (t2) {
    if (t2.spa) assertTierEntry("tier2.spa", t2.spa)
    if (t2.content_packs) assertTierEntry("tier2.content_packs", t2.content_packs)
  }
  if (t3 && t3.backend) assertTierEntry("tier3.backend", t3.backend)
  return raw as Manifest
}

function assertTierEntry(label: string, e: unknown): void {
  if (!e || typeof e !== "object") throw new ManifestError(`manifest: ${label} not an object`)
  const x = e as Record<string, unknown>
  for (const k of ["version", "url", "sha256", "size"]) {
    if (typeof x[k] !== "string" && typeof x[k] !== "number") {
      throw new ManifestError(`manifest: ${label}.${k} missing or wrong type`)
    }
  }
}

// ---------- version comparison ----------

/** Compare two semver-ish strings. Returns negative if a<b, positive if a>b,
 *  zero if equal. Trailing zero segments are normalized so "0.1" == "0.1.0". */
export function compareVersions(a: string, b: string): number {
  const split = (v: string) =>
    v.replace(/[^0-9a-zA-Z]+/g, ".").split(".").filter(Boolean).reduceRight(
      (acc, s) => (s === "0" && acc.length === 0 ? acc : [s, ...acc]),
      [] as string[],
    )
  const pa = split(a)
  const pb = split(b)
  const n = Math.max(pa.length, pb.length)
  for (let i = 0; i < n; i++) {
    const x = pa[i], y = pb[i]
    if (x === undefined) return -1
    if (y === undefined) return 1
    const nx = Number(x), ny = Number(y)
    if (!Number.isNaN(nx) && !Number.isNaN(ny)) {
      if (nx !== ny) return nx - ny
    } else if (x !== y) {
      return x < y ? -1 : 1
    }
  }
  return 0
}

// ---------- mirror fallback ----------

export interface MirrorFetchOpts {
  mirrors?: string[]
  signal?: AbortSignal
  timeoutMs?: number
}

/** Try each manifest URL in order; first 200 + parseable wins.
 *  Used to fall back across GH proxies when one is blocked. */
export async function fetchManifestWithMirrors(
  primaryUrl: string,
  mirrors: string[],
  opts: MirrorFetchOpts = {},
): Promise<{ manifest: Manifest; source: string }> {
  const path = stripOrigin(primaryUrl)
  const candidates = [primaryUrl, ...mirrors.map((m) => joinOrigin(m, path))]
  let lastErr: unknown = null
  for (const url of candidates) {
    try {
      const r = await fetch(url, { signal: opts.signal })
      if (!r.ok) throw new ManifestError(`manifest fetch ${r.status}`)
      const manifest = parseManifest(JSON.parse(await r.text()))
      return { manifest, source: url }
    } catch (e) {
      lastErr = e
    }
  }
  // Surface the underlying parse/validation error when present —
  // otherwise users see "all manifest sources failed" with no hint
  // about what went wrong (e.g. "unsupported manifest_version").
  const innerMsg = lastErr instanceof Error ? lastErr.message : String(lastErr)
  throw new ManifestError(`all manifest sources failed (last: ${innerMsg})`, { cause: lastErr })
}

function stripOrigin(url: string): string {
  const u = new URL(url)
  return u.pathname + u.search
}

function joinOrigin(base: string, p: string): string {
  return new URL(p, base).toString()
}

// ---------- helper: which tier entries are newer than current ----------

export interface CurrentVersions {
  app: string
  spa?: string
  content_packs?: string
  backend?: string
}

export interface AvailableUpdates {
  spa?: Tier2Entry
  content_packs?: Tier2Entry
  backend?: Tier3Entry
  /** True when current app version < manifest.min_app_version —
   *  caller must reject Tier 2/3 and route through Tier 1. */
  forceTier1: boolean
}

export function diffManifest(manifest: Manifest, current: CurrentVersions): AvailableUpdates {
  const out: AvailableUpdates = { forceTier1: compareVersions(current.app, manifest.min_app_version) < 0 }
  const t2 = manifest.tier2
  if (t2?.spa && (!current.spa || compareVersions(current.spa, t2.spa.version) < 0)) {
    out.spa = t2.spa
  }
  if (
    t2?.content_packs &&
    (!current.content_packs || compareVersions(current.content_packs, t2.content_packs.version) < 0)
  ) {
    out.content_packs = t2.content_packs
  }
  if (
    manifest.tier3?.backend &&
    (!current.backend || compareVersions(current.backend, manifest.tier3.backend.version) < 0)
  ) {
    out.backend = manifest.tier3.backend
  }
  return out
}
