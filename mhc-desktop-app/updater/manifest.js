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
exports.ManifestError = exports.defaultFetcher = void 0;
exports.parseManifest = parseManifest;
exports.compareVersions = compareVersions;
exports.fetchManifestWithMirrors = fetchManifestWithMirrors;
exports.diffManifest = diffManifest;
/** Default fetcher: native fetch with a timeout. Throws on non-2xx and
 *  on timeout. Caller catches. */
const defaultFetcher = async (url, init) => {
    const timeoutMs = init?.timeoutMs ?? 10_000;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
        const r = await fetch(url, { signal: init?.signal ?? controller.signal });
        if (!r.ok)
            throw new ManifestError(`manifest fetch ${r.status}`, { status: r.status, url });
        return {
            ok: r.ok,
            status: r.status,
            text: () => r.text(),
            arrayBuffer: () => r.arrayBuffer(),
        };
    }
    finally {
        clearTimeout(timer);
    }
};
exports.defaultFetcher = defaultFetcher;
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
    if (!raw || typeof raw !== "object") {
        throw new ManifestError("manifest: not an object");
    }
    const m = raw;
    if (m.manifest_version !== 1) {
        throw new ManifestError(`manifest: unsupported manifest_version=${String(m.manifest_version)}`);
    }
    if (m.channel !== "stable" && m.channel !== "beta") {
        throw new ManifestError(`manifest: invalid channel=${String(m.channel)}`);
    }
    if (typeof m.released_at !== "string") {
        throw new ManifestError("manifest: missing released_at");
    }
    if (typeof m.min_app_version !== "string") {
        throw new ManifestError("manifest: missing min_app_version");
    }
    // Tier 2 / 3 entries are independently optional, but if present must
    // be fully specified — partial entries would leave the client unsure
    // whether to skip or fail.
    const t2 = m.tier2;
    const t3 = m.tier3;
    if (t2) {
        if (t2.spa)
            assertTierEntry("tier2.spa", t2.spa);
        if (t2.content_packs)
            assertTierEntry("tier2.content_packs", t2.content_packs);
    }
    if (t3) {
        if (t3.backend)
            assertTierEntry("tier3.backend", t3.backend);
    }
    return raw;
}
function assertTierEntry(label, e) {
    if (!e || typeof e !== "object") {
        throw new ManifestError(`manifest: ${label} not an object`);
    }
    const x = e;
    for (const k of ["version", "url", "sha256", "size"]) {
        if (typeof x[k] !== "string" && typeof x[k] !== "number") {
            throw new ManifestError(`manifest: ${label}.${k} missing or wrong type`);
        }
    }
}
// ---------- version comparison ----------
/** Compare two semver-ish strings. Returns negative if a<b, positive if a>b,
 *  zero if equal. Tolerant of "2026-09-15" date versions and 0.x.y —
 *  split on '.' or '-' and compare segment-by-segment numerically when
 *  possible. Trailing zero segments are normalized away so "0.1" ==
 *  "0.1.0" matches semver semantics. */
function compareVersions(a, b) {
    const pa = stripTrailingZeros(tokenize(a));
    const pb = stripTrailingZeros(tokenize(b));
    const n = Math.max(pa.length, pb.length);
    for (let i = 0; i < n; i++) {
        const x = pa[i];
        const y = pb[i];
        if (x === undefined)
            return -1;
        if (y === undefined)
            return 1;
        const nx = Number(x);
        const ny = Number(y);
        if (!Number.isNaN(nx) && !Number.isNaN(ny)) {
            if (nx !== ny)
                return nx - ny;
        }
        else {
            if (x < y)
                return -1;
            if (x > y)
                return 1;
        }
    }
    return 0;
}
function tokenize(v) {
    return v
        .replace(/[^0-9a-zA-Z]+/g, ".")
        .split(".")
        .filter(Boolean);
}
function stripTrailingZeros(parts) {
    let end = parts.length;
    while (end > 0 && parts[end - 1] === "0")
        end--;
    return parts.slice(0, end);
}
/** Try each manifest URL in order; first 200 + parseable wins.
 *  Used to fall back across GH proxies when one is blocked.
 *  ``urlTemplate`` is ``{base}`` + the manifest path; we splice the
 *  origin out of ``primaryUrl`` and substitute the origin of each
 *  mirror. */
async function fetchManifestWithMirrors(primaryUrl, mirrors, opts = {}) {
    const fetcher = opts.fetcher ?? exports.defaultFetcher;
    const path = stripOrigin(primaryUrl);
    const candidates = [primaryUrl, ...mirrors.map((m) => joinOrigin(m, path))];
    let lastErr = null;
    for (const url of candidates) {
        try {
            const r = await fetcher(url, { signal: opts.signal, timeoutMs: opts.timeoutMs });
            const text = await r.text();
            const manifest = parseManifest(JSON.parse(text));
            return { manifest, source: url };
        }
        catch (e) {
            lastErr = e;
        }
    }
    throw new ManifestError("all manifest sources failed", { cause: lastErr });
}
function stripOrigin(url) {
    const u = new URL(url);
    return u.pathname + u.search;
}
function joinOrigin(base, p) {
    const u = new URL(p, base);
    return u.toString();
}
function diffManifest(manifest, current) {
    const out = { forceTier1: false };
    if (compareVersions(current.app, manifest.min_app_version) < 0) {
        out.forceTier1 = true;
    }
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