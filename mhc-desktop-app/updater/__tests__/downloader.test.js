"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
const node_test_1 = __importDefault(require("node:test"));
const strict_1 = __importDefault(require("node:assert/strict"));
const node_http_1 = require("node:http");
const node_crypto_1 = require("node:crypto");
const node_fs_1 = require("node:fs");
const node_os_1 = require("node:os");
const node_path_1 = require("node:path");
const downloader_1 = require("../downloader");
function startServer(handler) {
    return new Promise((resolve) => {
        const server = (0, node_http_1.createServer)(handler);
        server.listen(0, "127.0.0.1", () => {
            const port = server.address().port;
            resolve({
                server,
                url: `http://127.0.0.1:${port}`,
                close: () => new Promise((r) => server.close(() => r())),
            });
        });
    });
}
const PAYLOAD = Buffer.from("hello world".repeat(1024));
const PAYLOAD_SHA = (0, node_crypto_1.createHash)("sha256").update(PAYLOAD).digest("hex");
(0, node_test_1.default)("downloadToFile: writes file with correct sha256", async () => {
    const tmp = await node_fs_1.promises.mkdtemp((0, node_path_1.join)((0, node_os_1.tmpdir)(), "mhc-dl-"));
    try {
        const { url, close } = await startServer((_req, res) => {
            res.writeHead(200, { "content-length": String(PAYLOAD.length), "content-type": "application/octet-stream" });
            res.end(PAYLOAD);
        });
        const dest = (0, node_path_1.join)(tmp, "x.bin");
        const r = await (0, downloader_1.downloadToFile)(url + "/x.bin", dest, { expectedSha256: PAYLOAD_SHA });
        strict_1.default.equal(r.sha256, PAYLOAD_SHA);
        strict_1.default.equal(r.bytes, PAYLOAD.length);
        const data = await node_fs_1.promises.readFile(dest);
        strict_1.default.equal(data.length, PAYLOAD.length);
        await close();
    }
    finally {
        await node_fs_1.promises.rm(tmp, { recursive: true, force: true });
    }
});
(0, node_test_1.default)("downloadToFile: fails on HTTP 404", async () => {
    const tmp = await node_fs_1.promises.mkdtemp((0, node_path_1.join)((0, node_os_1.tmpdir)(), "mhc-dl-"));
    try {
        const { url, close } = await startServer((_req, res) => {
            res.writeHead(404);
            res.end();
        });
        await strict_1.default.rejects((0, downloader_1.downloadToFile)(url + "/missing", (0, node_path_1.join)(tmp, "x.bin")), (err) => err instanceof downloader_1.DownloadError && /HTTP 404/.test(err.message));
        await close();
    }
    finally {
        await node_fs_1.promises.rm(tmp, { recursive: true, force: true });
    }
});
(0, node_test_1.default)("downloadToFile: fails on sha256 mismatch", async () => {
    const tmp = await node_fs_1.promises.mkdtemp((0, node_path_1.join)((0, node_os_1.tmpdir)(), "mhc-dl-"));
    try {
        const { url, close } = await startServer((_req, res) => {
            res.writeHead(200);
            res.end(PAYLOAD);
        });
        const wrong = "0".repeat(64);
        await strict_1.default.rejects((0, downloader_1.downloadToFile)(url + "/x", (0, node_path_1.join)(tmp, "x.bin"), { expectedSha256: wrong }), (err) => err instanceof downloader_1.DownloadError && /sha256 mismatch/.test(err.message));
        // .part file should remain for diagnostics.
        strict_1.default.equal(await node_fs_1.promises.stat((0, node_path_1.join)(tmp, "x.bin.part")).then(() => true).catch(() => false), true);
        await close();
    }
    finally {
        await node_fs_1.promises.rm(tmp, { recursive: true, force: true });
    }
});
(0, node_test_1.default)("downloadToFile: server abort mid-stream rejects", async () => {
    const tmp = await node_fs_1.promises.mkdtemp((0, node_path_1.join)((0, node_os_1.tmpdir)(), "mhc-dl-"));
    try {
        const { url, close } = await startServer((req, res) => {
            // Send partial, then hang up abruptly.
            res.writeHead(200);
            res.write(PAYLOAD.subarray(0, 100));
            setImmediate(() => {
                req.socket.destroy();
                res.end();
            });
        });
        await strict_1.default.rejects((0, downloader_1.downloadToFile)(url + "/x", (0, node_path_1.join)(tmp, "x.bin")), downloader_1.DownloadError);
        await close();
    }
    finally {
        await node_fs_1.promises.rm(tmp, { recursive: true, force: true });
    }
});
(0, node_test_1.default)("downloadToFile: cancel via AbortSignal", async () => {
    const tmp = await node_fs_1.promises.mkdtemp((0, node_path_1.join)((0, node_os_1.tmpdir)(), "mhc-dl-"));
    try {
        let pending = null;
        const { url, close } = await startServer((req, res) => {
            pending = res;
            res.writeHead(200);
            // Slow drip so we have time to abort.
            let i = 0;
            const id = setInterval(() => {
                if (i++ > 100) {
                    clearInterval(id);
                    res.end();
                    return;
                }
                res.write(Buffer.alloc(1024, 0x61));
            }, 20);
            req.on("close", () => clearInterval(id));
        });
        const ctrl = new AbortController();
        setTimeout(() => ctrl.abort(), 100);
        await strict_1.default.rejects((0, downloader_1.downloadToFile)(url + "/x", (0, node_path_1.join)(tmp, "x.bin"), { signal: ctrl.signal }), downloader_1.DownloadError);
        if (pending) {
            try {
                pending.end();
            }
            catch { /* ignore */ }
        }
        await close();
    }
    finally {
        await node_fs_1.promises.rm(tmp, { recursive: true, force: true });
    }
});
(0, node_test_1.default)("downloadToFile: creates parent dirs", async () => {
    const tmp = await node_fs_1.promises.mkdtemp((0, node_path_1.join)((0, node_os_1.tmpdir)(), "mhc-dl-"));
    try {
        const { url, close } = await startServer((_req, res) => {
            res.writeHead(200);
            res.end(PAYLOAD);
        });
        const dest = (0, node_path_1.join)(tmp, "deeply", "nested", "x.bin");
        await (0, downloader_1.downloadToFile)(url + "/x", dest);
        strict_1.default.ok(await node_fs_1.promises.stat(dest));
        await close();
    }
    finally {
        await node_fs_1.promises.rm(tmp, { recursive: true, force: true });
    }
});
(0, node_test_1.default)("downloadToFile: reports progress bytes", async () => {
    const tmp = await node_fs_1.promises.mkdtemp((0, node_path_1.join)((0, node_os_1.tmpdir)(), "mhc-dl-"));
    try {
        const { url, close } = await startServer((_req, res) => {
            res.writeHead(200, { "content-length": String(PAYLOAD.length) });
            res.end(PAYLOAD);
        });
        const seen = [];
        await (0, downloader_1.downloadToFile)(url + "/x", (0, node_path_1.join)(tmp, "x.bin"), {
            onProgress: (n) => seen.push(n),
            contentLength: PAYLOAD.length,
        });
        strict_1.default.ok(seen.length >= 1, "progress should fire at least once");
        strict_1.default.equal(seen[seen.length - 1], PAYLOAD.length, "final progress should be full size");
        await close();
    }
    finally {
        await node_fs_1.promises.rm(tmp, { recursive: true, force: true });
    }
});
//# sourceMappingURL=downloader.test.js.map