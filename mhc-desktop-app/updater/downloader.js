"use strict";
/**
 * Tier 2/3 payload downloader — fetches tar.gz from a manifest URL
 * into a local file, verifies SHA-256, reports progress.
 *
 * No Electron deps. Tests run under plain `node --test` against a
 * loopback http server.
 *
 * Progress is reported via an optional callback so the tray menu /
 * settings UI can show "downloading 47%". We don't bother with
 * download resumption (HTTP Range) — payloads are <70 MB and a
 * dropped connection retries from scratch. If that ever becomes a
 * problem, the entry point is ``downloadToFile()`` below.
 *
 * We deliberately bypass the Fetcher abstraction here: the test
 * path is a real local http server (more realistic), and the
 * production path is global ``fetch()``. Streaming via Web
 * ReadableStream -> Node Readable gives us proper backpressure
 * without buffering 70 MB in RAM.
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.DownloadError = void 0;
exports.downloadToFile = downloadToFile;
const node_fs_1 = require("node:fs");
const node_path_1 = require("node:path");
const promises_1 = require("node:stream/promises");
const node_stream_1 = require("node:stream");
const node_crypto_1 = require("node:crypto");
class DownloadError extends Error {
    cause;
    constructor(msg, opts) {
        super(msg);
        this.name = "DownloadError";
        if (opts?.cause !== undefined)
            this.cause = opts.cause;
    }
}
exports.DownloadError = DownloadError;
/** Download ``url`` to ``dest``. Returns the SHA-256 (hex) of what was
 *  actually written. ``dest``'s parent dirs are created. The temp
 *  file is named ``dest + '.part'`` until the SHA verifies — then
 *  renamed to ``dest``. A failed / interrupted download leaves
 *  ``dest`` untouched and the ``.part`` file for post-mortem. */
async function downloadToFile(url, dest, opts = {}) {
    await node_fs_1.promises.mkdir((0, node_path_1.dirname)(dest), { recursive: true });
    const partPath = dest + ".part";
    const hash = (0, node_crypto_1.createHash)("sha256");
    let written = 0;
    const reportEvery = 256 * 1024;
    let lastReport = 0;
    const ctrl = new AbortController();
    opts.signal?.addEventListener("abort", () => ctrl.abort());
    const timer = setTimeout(() => ctrl.abort(), opts.timeoutMs ?? 5 * 60 * 1000);
    let resp;
    // Fast-path: caller already aborted before we started.
    if (opts.signal?.aborted) {
        clearTimeout(timer);
        throw new DownloadError(`download ${url} aborted by caller`, { cause: new Error("aborted") });
    }
    try {
        resp = await fetch(url, { signal: ctrl.signal });
    }
    catch (e) {
        clearTimeout(timer);
        const aborted = opts.signal?.aborted === true || ctrl.signal.aborted;
        const reason = aborted ? "aborted by caller" : e.message;
        throw new DownloadError(`download ${url} ${aborted ? "" : "failed: "}${reason}`, { cause: e });
    }
    if (!resp.ok || !resp.body) {
        clearTimeout(timer);
        throw new DownloadError(`download ${url} -> HTTP ${resp.status}`);
    }
    const total = opts.contentLength ?? (Number(resp.headers.get("content-length") ?? "0") || undefined);
    const nodeStream = node_stream_1.Readable.fromWeb(resp.body);
    nodeStream.on("data", (chunk) => {
        const buf = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
        hash.update(buf);
        written += buf.byteLength;
        if (opts.onProgress && written - lastReport >= reportEvery) {
            lastReport = written;
            if (total && total > 0)
                opts.onProgress(written);
        }
    });
    try {
        await (0, promises_1.pipeline)(nodeStream, (0, node_fs_1.createWriteStream)(partPath));
    }
    catch (e) {
        clearTimeout(timer);
        throw new DownloadError(`write ${partPath} failed: ${e.message}`, { cause: e });
    }
    clearTimeout(timer);
    // Final progress tick so UI knows we're at 100%.
    if (opts.onProgress) {
        if (total && total > 0)
            opts.onProgress(total);
        else
            opts.onProgress(written);
    }
    const sha256 = hash.digest("hex");
    if (opts.expectedSha256 && sha256 !== opts.expectedSha256.toLowerCase()) {
        throw new DownloadError(`sha256 mismatch: expected ${opts.expectedSha256} got ${sha256}`);
    }
    // Atomic: rename part -> dest on the same volume.
    await node_fs_1.promises.rename(partPath, dest);
    return { sha256, bytes: written };
}
//# sourceMappingURL=downloader.js.map