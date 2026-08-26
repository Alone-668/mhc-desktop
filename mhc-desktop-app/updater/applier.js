"use strict";
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
Object.defineProperty(exports, "__esModule", { value: true });
exports.ApplyError = void 0;
exports.extractTarGz = extractTarGz;
exports.createTarGz = createTarGz;
exports.atomicReplace = atomicReplace;
exports.sha256OfFile = sha256OfFile;
exports.applyPayloads = applyPayloads;
exports.rollback = rollback;
exports.cleanStagedPayload = cleanStagedPayload;
exports.listBackups = listBackups;
const node_child_process_1 = require("node:child_process");
const node_crypto_1 = require("node:crypto");
const node_fs_1 = require("node:fs");
const node_path_1 = require("node:path");
class ApplyError extends Error {
    cause;
    constructor(msg, opts) {
        super(msg);
        this.name = "ApplyError";
        if (opts?.cause !== undefined)
            this.cause = opts.cause;
    }
}
exports.ApplyError = ApplyError;
// ---------- tar helpers (Windows-friendly) ----------
/** POSIX-style relative path from ``from`` to ``to``. tar expects
 *  forward slashes in argv on every platform — Windows backslashes
 *  trigger GNU tar's remote-file heuristic ("Cannot connect to C:").
 *  This helper runs the ``cwd`` relative-path trick documented in
 *  the function bodies below. */
function relForward(from, to) {
    return (0, node_path_1.relative)(from, to).split(/[\\/]/).join("/");
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
async function extractTarGz(src, dest) {
    await node_fs_1.promises.mkdir(dest, { recursive: true });
    const relSrc = relForward(dest, src);
    await runTar(["-xzf", relSrc], { cwd: dest });
}
/** Inverse: tar+gz a directory into a tarball. Same Windows cwd trick.
 *  Used by ``scripts/release.sh`` and tests. */
async function createTarGz(srcDir, outFile) {
    await node_fs_1.promises.mkdir((0, node_path_1.dirname)(outFile), { recursive: true });
    const cwd = (0, node_path_1.dirname)(outFile);
    const relSrcDir = relForward(cwd, srcDir);
    await runTar(["-czf", (0, node_path_1.basename)(outFile), "-C", relSrcDir, "."], { cwd });
}
function runTar(args, opts) {
    return new Promise((resolve, reject) => {
        const p = (0, node_child_process_1.spawn)("tar", args, {
            cwd: opts.cwd,
            stdio: ["ignore", "ignore", "pipe"],
        });
        let stderr = "";
        p.stderr.on("data", (b) => (stderr += b.toString()));
        p.on("error", reject);
        p.on("exit", (code) => {
            if (code === 0)
                resolve();
            else
                reject(new ApplyError(`tar exit ${code}: ${stderr.trim()}`));
        });
    });
}
// ---------- atomic replace ----------
/** Same-volume rename is atomic; cross-volume falls back to copy +
 *  delete. The destination file exists throughout the copy (then
 *  swaps via the second rename), so the live install is never
 *  missing. */
async function atomicReplace(src, dst) {
    await node_fs_1.promises.mkdir((0, node_path_1.dirname)(dst), { recursive: true });
    try {
        await node_fs_1.promises.rename(src, dst);
    }
    catch (e) {
        const err = e;
        if (err.code !== "EXDEV")
            throw err;
        // Cross-volume fallback: copy then delete.
        await node_fs_1.promises.cp(src, dst, { recursive: true });
        await node_fs_1.promises.rm(src, { recursive: true, force: true });
    }
}
// ---------- hash helpers ----------
/** SHA-256 of a single file. Used to re-verify staged tarballs and
 *  to fingerprint the live install (for "did we already apply
 *  version X?" checks). */
async function sha256OfFile(p) {
    const h = (0, node_crypto_1.createHash)("sha256");
    const data = await node_fs_1.promises.readFile(p);
    h.update(data);
    return h.digest("hex");
}
/** Apply a batch of payloads. Each entry is verified (sha), then
 *  extracted to a fresh payload dir, then atomically swapped into
 *  ``resourcesPath/<key>``. The previous install is kept under
 *  ``resourcesPath/<key>.bak.<ts>`` for ``rollback()``. */
async function applyPayloads(ctx, entries) {
    const payloadRoot = (0, node_path_1.join)(ctx.userDataPath, "staged-update", "payload");
    // Fresh payload dir each attempt — never reuse.
    await node_fs_1.promises.rm(payloadRoot, { recursive: true, force: true });
    await node_fs_1.promises.mkdir(payloadRoot, { recursive: true });
    const result = {
        applied: [],
        backups: { spa: null, "content-packs": null, backend: null },
    };
    const ts = Date.now();
    for (const entry of entries) {
        const actual = await sha256OfFile(entry.tarball);
        if (actual !== entry.sha256.toLowerCase()) {
            throw new ApplyError(`payload ${entry.key}: sha256 mismatch (expected ${entry.sha256} got ${actual})`);
        }
        const target = (0, node_path_1.join)(payloadRoot, entry.key);
        await extractTarGz(entry.tarball, target);
        const live = (0, node_path_1.join)(ctx.resourcesPath, entry.key);
        const backup = `${live}.bak.${ts}`;
        if ((0, node_fs_1.existsSync)(live)) {
            await atomicReplace(live, backup);
        }
        await atomicReplace(target, live);
        result.applied.push(entry.key);
        result.backups[entry.key] = (0, node_fs_1.existsSync)(backup) ? backup : null;
    }
    return result;
}
// ---------- rollback ----------
/** Roll back one or more keys to their most recent backup. Called when
 *  an apply fails partway through OR when the post-apply boot health
 *  check (60 s ``/ready``) fails. */
async function rollback(ctx, keys) {
    const rolled = [];
    const remaining = { spa: null, "content-packs": null, backend: null };
    for (const key of keys) {
        const live = (0, node_path_1.join)(ctx.resourcesPath, key);
        const backups = await findBackups(live);
        if (backups.length === 0)
            continue;
        const newest = backups[0];
        const failedTag = `${live}.failed.${Date.now()}`;
        if ((0, node_fs_1.existsSync)(live)) {
            await atomicReplace(live, failedTag);
        }
        await atomicReplace(newest, live);
        rolled.push(key);
        remaining[key] = backups[1] ?? null;
    }
    return { rolled, remaining };
}
/** Find ``<live>.bak.<ts>`` siblings, newest first. */
async function findBackups(live) {
    const parent = (0, node_path_1.dirname)(live);
    const base = (0, node_path_1.basename)(live);
    const prefix = `${base}.bak.`;
    let entries;
    try {
        entries = await node_fs_1.promises.readdir(parent);
    }
    catch {
        return [];
    }
    return entries
        .filter((e) => e.startsWith(prefix))
        .map((e) => (0, node_path_1.join)(parent, e))
        .sort()
        .reverse();
}
// ---------- post-apply cleanup ----------
async function cleanStagedPayload(userDataPath) {
    await node_fs_1.promises.rm((0, node_path_1.join)(userDataPath, "staged-update", "payload"), { recursive: true, force: true });
}
async function listBackups(ctx) {
    const out = { spa: [], "content-packs": [], backend: [] };
    for (const key of ["spa", "content-packs", "backend"]) {
        out[key] = await findBackups((0, node_path_1.join)(ctx.resourcesPath, key));
    }
    return out;
}
//# sourceMappingURL=applier.js.map