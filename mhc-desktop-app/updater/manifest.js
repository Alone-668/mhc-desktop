"use strict";
/**
 * Manifest types + fetch + validation.
 *
 * Pure logic, no Electron deps — tests run under plain `node --test`.
 *
 * Manifest shape lives in `docs/UPDATE-MECHANISM.md` §3. Anything we
 * change here must also update that doc; the manifest is the public
 * contract between the release pipeline and every installed client.
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.ManifestError = void 0;
exports.parseManifest = parseManifest;
exports.compareVersions = compareVersions;
exports.fetchManifestWithMirrors = fetchManifestWithMirrors;
exports.diffManifest = diffManifest;
// ---------- validation ----------
class ManifestError extends Error {
    cause;
    constructor(msg, opts) {
        super(msg);
        this.name = "ManifestError";
        if (opts?.cause !== undefined)
            this.cause = opts.cause;
    }
}
exports.ManifestError = ManifestError;
function parseManifest(raw) {
    if (!raw || typeof raw !== "object")
        throw new ManifestError("manifest: not an object");
    const m = raw;
    if (m.manifest_version !== 1) {
        throw new ManifestError(`manifest: unsupported manifest_version=${String(m.manifest_version)}`);
    }
    if (m.channel !== "stable" && m.channel !== "beta") {
        throw new ManifestError(`manifest: invalid channel=${String(m.channel)}`);
    }
    if (typeof m.released_at !== "string")
        throw new ManifestError("manifest: missing released_at");
    if (typeof m.min_app_version !== "string")
        throw new ManifestError("manifest: missing min_app_version");
    // Tier 2/3 entries are independently optional but if present must
    // be fully specified — partial entries leave the client unsure
    // whether to skip or fail.
    const t2 = m.tier2;
    const t3 = m.tier3;
    if (t2) {
        if (t2.spa)
            assertTierEntry("tier2.spa", t2.spa);
        if (t2.content_packs)
            assertTierEntry("tier2.content_packs", t2.content_packs);
    }
    if (t3 && t3.backend)
        assertTierEntry("tier3.backend", t3.backend);
    return raw;
}
function assertTierEntry(label, e) {
    if (!e || typeof e !== "object")
        throw new ManifestError(`manifest: ${label} not an object`);
    const x = e;
    for (const k of ["version", "url", "sha256", "size"]) {
        if (typeof x[k] !== "string" && typeof x[k] !== "number") {
            throw new ManifestError(`manifest: ${label}.${k} missing or wrong type`);
        }
    }
}
// ---------- version comparison ----------
/** Compare two semver-ish strings. Returns negative if a<b, positive if a>b,
 *  zero if equal. Trailing zero segments are normalized so "0.1" == "0.1.0". */
function compareVersions(a, b) {
    const split = (v) => v.replace(/[^0-9a-zA-Z]+/g, ".").split(".").filter(Boolean).reduceRight((acc, s) => (s === "0" && acc.length === 0 ? acc : [s, ...acc]), []);
    const pa = split(a);
    const pb = split(b);
    const n = Math.max(pa.length, pb.length);
    for (let i = 0; i < n; i++) {
        const x = pa[i], y = pb[i];
        if (x === undefined)
            return -1;
        if (y === undefined)
            return 1;
        const nx = Number(x), ny = Number(y);
        if (!Number.isNaN(nx) && !Number.isNaN(ny)) {
            if (nx !== ny)
                return nx - ny;
        }
        else if (x !== y) {
            return x < y ? -1 : 1;
        }
    }
    return 0;
}
/** Try each manifest URL in order; first 200 + parseable wins.
 *  Used to fall back across GH proxies when one is blocked. */
async function fetchManifestWithMirrors(primaryUrl, mirrors, opts = {}) {
    const path = stripOrigin(primaryUrl);
    const candidates = [primaryUrl, ...mirrors.map((m) => joinOrigin(m, path))];
    let lastErr = null;
    for (const url of candidates) {
        try {
            const r = await fetch(url, { signal: opts.signal });
            if (!r.ok)
                throw new ManifestError(`manifest fetch ${r.status}`);
            const manifest = parseManifest(JSON.parse(await r.text()));
            return { manifest, source: url };
        }
        catch (e) {
            lastErr = e;
        }
    }
    // Surface the underlying parse/validation error when present —
    // otherwise users see "all manifest sources failed" with no hint
    // about what went wrong (e.g. "unsupported manifest_version").
    const innerMsg = lastErr instanceof Error ? lastErr.message : String(lastErr);
    throw new ManifestError(`all manifest sources failed (last: ${innerMsg})`, { cause: lastErr });
}
function stripOrigin(url) {
    const u = new URL(url);
    return u.pathname + u.search;
}
function joinOrigin(base, p) {
    return new URL(p, base).toString();
}
function diffManifest(manifest, current) {
    const out = { forceTier1: compareVersions(current.app, manifest.min_app_version) < 0 };
    const t2 = manifest.tier2;
    if (t2?.spa && (!current.spa || compareVersions(current.spa, t2.spa.version) < 0)) {
        out.spa = t2.spa;
    }
    if (t2?.content_packs &&
        (!current.content_packs || compareVersions(current.content_packs, t2.content_packs.version) < 0)) {
        out.content_packs = t2.content_packs;
    }
    if (manifest.tier3?.backend &&
        (!current.backend || compareVersions(current.backend, manifest.tier3.backend.version) < 0)) {
        out.backend = manifest.tier3.backend;
    }
    return out;
}
//# sourceMappingURL=manifest.js.map