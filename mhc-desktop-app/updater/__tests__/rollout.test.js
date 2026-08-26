"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
const node_test_1 = __importDefault(require("node:test"));
const strict_1 = __importDefault(require("node:assert/strict"));
const node_fs_1 = require("node:fs");
const node_os_1 = require("node:os");
const node_path_1 = require("node:path");
const node_events_1 = require("node:events");
const node_crypto_1 = require("node:crypto");
const rollout_1 = require("../rollout");
const applier_1 = require("../applier");
const log_1 = require("../log");
const VALID = {
    manifest_version: 1,
    channel: "stable",
    released_at: "2026-09-15T08:00:00+08:00",
    min_app_version: "0.1.0",
    tier2: {
        spa: { version: "0.2.1", url: "https://cdn/spa.tgz", sha256: "a".repeat(64), size: 100 },
        content_packs: { version: "2026-09-15", url: "https://cdn/cp.tgz", sha256: "b".repeat(64), size: 200 },
    },
    tier3: {
        backend: { version: "0.2.1", url: "https://cdn/be.tgz", sha256: "c".repeat(64), size: 300 },
    },
};
const FAKE_PREF = {
    manifestUrl: "https://primary.example.com/update.json",
    channel: "stable",
    autoUpdate: true,
    checkIntervalMs: 60_000,
};
async function makeCtx(overrides = {}) {
    const root = await node_fs_1.promises.mkdtemp((0, node_path_1.join)((0, node_os_1.tmpdir)(), "mhc-rollout-"));
    const resourcesPath = (0, node_path_1.join)(root, "resources");
    const userDataPath = (0, node_path_1.join)(root, "userData");
    await node_fs_1.promises.mkdir(resourcesPath, { recursive: true });
    await node_fs_1.promises.mkdir(userDataPath, { recursive: true });
    // Each ctx gets its own prefs copy so a test that mutates
    // ``ctx.prefs.autoUpdate = false`` doesn't leak into the next test.
    const prefs = { ...FAKE_PREF };
    return {
        resourcesPath,
        userDataPath,
        appVersion: "0.1.0",
        current: { app: "0.1.0" },
        prefs,
        defaultManifestUrl: FAKE_PREF.manifestUrl,
        mirrors: ["https://mirror.example.com"],
        checkIntervalMs: 60_000,
        ...overrides,
        cleanup: async () => node_fs_1.promises.rm(root, { recursive: true, force: true }),
    };
}
/** Build a fake manifest fetcher that returns the given manifest on
 *  the first call. */
function fakeManifestFetcher(manifest, err) {
    return async (url) => {
        if (err)
            throw err;
        return {
            ok: true,
            status: 200,
            text: async () => JSON.stringify(manifest),
            arrayBuffer: async () => new ArrayBuffer(0),
        };
    };
}
async function makeTarball(outFile, content) {
    const stage = outFile + ".stage";
    await node_fs_1.promises.mkdir(stage, { recursive: true });
    for (const [name, body] of Object.entries(content)) {
        await node_fs_1.promises.writeFile((0, node_path_1.join)(stage, name), body);
    }
    await (0, applier_1.createTarGz)(stage, outFile);
    await node_fs_1.promises.rm(stage, { recursive: true, force: true });
    return (0, node_crypto_1.createHash)("sha256").update(await node_fs_1.promises.readFile(outFile)).digest("hex");
}
// ----- tests -----
(0, node_test_1.default)("rollout: checkNow transitions idle -> checking -> update_available when updates exist", async () => {
    const ctx = await makeCtx();
    const origFetch = globalThis.fetch;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    globalThis.fetch = (async (url) => {
        if (String(url).includes("update.json")) {
            return {
                ok: true,
                status: 200,
                text: async () => JSON.stringify(VALID),
                arrayBuffer: async () => new ArrayBuffer(0),
                headers: new Map(),
            };
        }
        return origFetch(url);
    });
    try {
        const log = (0, log_1.createMemoryLogger)();
        const states = [];
        const handle = (0, rollout_1.createRollout)(ctx, {
            logger: log,
            onState: (i) => states.push(i.state),
            // Avoid the auto-loop firing in tests.
            setIntervalFn: (() => 0),
        });
        const r = await handle.checkNow();
        strict_1.default.equal(r.state, "update_available");
        strict_1.default.ok(r.available?.spa);
        strict_1.default.ok(r.available?.content_packs);
        strict_1.default.ok(r.available?.backend);
        strict_1.default.ok(states.includes("checking"));
        strict_1.default.ok(states.includes("update_available"));
    }
    finally {
        globalThis.fetch = origFetch;
        await ctx.cleanup();
    }
});
(0, node_test_1.default)("rollout: checkNow transitions to download_failed when manifest unreachable", async () => {
    const ctx = await makeCtx();
    const origFetch = globalThis.fetch;
    globalThis.fetch = (async () => ({ ok: false, status: 500, text: async () => "", arrayBuffer: async () => new ArrayBuffer(0), headers: new Map() }));
    try {
        const handle = (0, rollout_1.createRollout)(ctx, { setIntervalFn: (() => 0) });
        const r = await handle.checkNow();
        strict_1.default.equal(r.state, "download_failed");
        strict_1.default.ok(r.error);
    }
    finally {
        globalThis.fetch = origFetch;
        await ctx.cleanup();
    }
});
(0, node_test_1.default)("rollout: checkNow returns idle when nothing newer", async () => {
    const ctx = await makeCtx({
        current: {
            app: "0.1.0",
            spa: "0.2.1",
            content_packs: "2026-09-15",
            backend: "0.2.1",
        },
    });
    const origFetch = globalThis.fetch;
    globalThis.fetch = (async () => ({ ok: true, status: 200, text: async () => JSON.stringify(VALID), arrayBuffer: async () => new ArrayBuffer(0), headers: new Map() }));
    try {
        const handle = (0, rollout_1.createRollout)(ctx, { setIntervalFn: (() => 0) });
        const r = await handle.checkNow();
        strict_1.default.equal(r.state, "idle");
        strict_1.default.equal(r.available, undefined);
    }
    finally {
        globalThis.fetch = origFetch;
        await ctx.cleanup();
    }
});
(0, node_test_1.default)("rollout: forceTier1 when app below min_app_version", async () => {
    const ctx = await makeCtx({ appVersion: "0.0.9", current: { app: "0.0.9" } });
    const origFetch = globalThis.fetch;
    globalThis.fetch = (async () => ({ ok: true, status: 200, text: async () => JSON.stringify(VALID), arrayBuffer: async () => new ArrayBuffer(0), headers: new Map() }));
    try {
        const handle = (0, rollout_1.createRollout)(ctx, { setIntervalFn: (() => 0) });
        const r = await handle.checkNow();
        strict_1.default.equal(r.state, "update_available");
        strict_1.default.equal(r.forceTier1, true);
    }
    finally {
        globalThis.fetch = origFetch;
        await ctx.cleanup();
    }
});
(0, node_test_1.default)("rollout: respects autoUpdate=false", async () => {
    const ctx = await makeCtx();
    ctx.prefs.autoUpdate = false;
    try {
        const handle = (0, rollout_1.createRollout)(ctx, { setIntervalFn: (() => 0) });
        const r = await handle.checkNow();
        strict_1.default.equal(r.state, "idle");
    }
    finally {
        await ctx.cleanup();
    }
});
(0, node_test_1.default)("rollout: installAvailable downloads via stubbed fetch", async () => {
    const ctx = await makeCtx();
    // Pre-make a tarball on disk.
    const stagedDir = (0, node_path_1.join)(ctx.userDataPath, "staged-update");
    await node_fs_1.promises.mkdir(stagedDir, { recursive: true });
    const tarPath = (0, node_path_1.join)(stagedDir, "spa.tar.gz.src");
    const tarSha = await makeTarball(tarPath, { "index.html": "<html>v2</html>" });
    const tarBytes = await node_fs_1.promises.readFile(tarPath);
    // Manifest with the URL pointing at a path we'll intercept in
    // fetch. The url host doesn't matter; the fetcher just needs to
    // match by suffix.
    const m = {
        ...VALID,
        tier2: {
            spa: { version: "99.0.0", url: "http://stubhost/spa.tar.gz", sha256: tarSha, size: tarBytes.length },
        },
        tier3: undefined,
    };
    const origFetch = globalThis.fetch;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    globalThis.fetch = (async (url) => {
        const s = String(url);
        if (s.endsWith("update.json")) {
            return { ok: true, status: 200, text: async () => JSON.stringify(m), arrayBuffer: async () => new ArrayBuffer(0), headers: new Map([["content-length", "100"]]) };
        }
        if (s.endsWith("spa.tar.gz")) {
            return {
                ok: true,
                status: 200,
                body: new ReadableStream({
                    start(c) { c.enqueue(new Uint8Array(tarBytes)); c.close(); },
                }),
                headers: new Map([["content-length", String(tarBytes.length)]]),
            };
        }
        return { ok: false, status: 404, text: async () => "", arrayBuffer: async () => new ArrayBuffer(0), headers: new Map() };
    });
    try {
        const log = (0, log_1.createMemoryLogger)();
        const handle = (0, rollout_1.createRollout)(ctx, { logger: log, setIntervalFn: (() => 0) });
        await handle.checkNow();
        const r = await handle.installAvailable();
        strict_1.default.equal(r.state, "staged");
        // Staged manifest + tarball present
        const stagedManifest = JSON.parse(await node_fs_1.promises.readFile((0, node_path_1.join)(stagedDir, "manifest.json"), "utf8"));
        strict_1.default.equal(stagedManifest.tier2.spa.version, "99.0.0");
        strict_1.default.ok(await node_fs_1.promises.stat((0, node_path_1.join)(stagedDir, "spa.tar.gz")));
    }
    finally {
        globalThis.fetch = origFetch;
        await ctx.cleanup();
    }
});
(0, node_test_1.default)("rollout: installAvailable fails download when sha mismatches", async () => {
    const ctx = await makeCtx();
    const stagedDir = (0, node_path_1.join)(ctx.userDataPath, "staged-update");
    await node_fs_1.promises.mkdir(stagedDir, { recursive: true });
    const tarPath = (0, node_path_1.join)(stagedDir, "spa.tar.gz.src");
    const tarSha = await makeTarball(tarPath, { "index.html": "<html>v2</html>" });
    const tarBytes = await node_fs_1.promises.readFile(tarPath);
    const wrongSha = "0".repeat(64);
    const m = {
        ...VALID,
        tier2: { spa: { version: "99.0.0", url: "http://stubhost/spa.tar.gz", sha256: wrongSha, size: tarBytes.length } },
        tier3: undefined,
    };
    const origFetch = globalThis.fetch;
    globalThis.fetch = (async (url) => {
        const s = String(url);
        if (s.endsWith("update.json"))
            return { ok: true, status: 200, text: async () => JSON.stringify(m), arrayBuffer: async () => new ArrayBuffer(0), headers: new Map() };
        if (s.endsWith("spa.tar.gz")) {
            return { ok: true, status: 200, body: new ReadableStream({ start(c) { c.enqueue(new Uint8Array(tarBytes)); c.close(); } }), headers: new Map([["content-length", String(tarBytes.length)]]) };
        }
        return { ok: false, status: 404, text: async () => "", arrayBuffer: async () => new ArrayBuffer(0), headers: new Map() };
    });
    try {
        const handle = (0, rollout_1.createRollout)(ctx, { setIntervalFn: (() => 0) });
        await handle.checkNow();
        await strict_1.default.rejects(handle.installAvailable(), /sha256 mismatch/);
    }
    finally {
        globalThis.fetch = origFetch;
        await ctx.cleanup();
    }
});
(0, node_test_1.default)("rollout: applyPending swaps live with staged and writes last-good on commit", async () => {
    const ctx = await makeCtx();
    // Pre-populate live spa with v1.
    const live = (0, node_path_1.join)(ctx.resourcesPath, "spa");
    await node_fs_1.promises.mkdir(live, { recursive: true });
    await node_fs_1.promises.writeFile((0, node_path_1.join)(live, "index.html"), "<html>v1</html>");
    // Stage a v2 tarball.
    const stagedDir = (0, node_path_1.join)(ctx.userDataPath, "staged-update");
    await node_fs_1.promises.mkdir(stagedDir, { recursive: true });
    const tarPath = (0, node_path_1.join)(stagedDir, "spa.tar.gz");
    const sha = await makeTarball(tarPath, { "index.html": "<html>v2</html>" });
    // Write a staged manifest so applyPending finds something.
    const m = {
        ...VALID,
        tier2: { spa: { version: "0.2.1", url: "http://stubhost/spa.tar.gz", sha256: sha, size: 9999 } },
        tier3: undefined,
    };
    await node_fs_1.promises.writeFile((0, node_path_1.join)(stagedDir, "manifest.json"), JSON.stringify(m));
    const handle = (0, rollout_1.createRollout)(ctx, { setIntervalFn: (() => 0) });
    const r = await handle.applyPending();
    strict_1.default.deepEqual(r.applied, ["spa"]);
    strict_1.default.equal(await node_fs_1.promises.readFile((0, node_path_1.join)(ctx.resourcesPath, "spa", "index.html"), "utf8"), "<html>v2</html>");
    // State should be committed; last-good.json written only after
    // commitIfHealthy is called by main.ts.
    strict_1.default.equal(handle.getInfo().state, "committed");
    await handle.commitIfHealthy({ versions: { spa: "0.2.1" } });
    const lg = JSON.parse(await node_fs_1.promises.readFile((0, node_path_1.join)(ctx.userDataPath, "last-good.json"), "utf8"));
    strict_1.default.equal(lg.spa, "0.2.1");
    strict_1.default.equal(lg.app, "0.1.0");
    await ctx.cleanup();
});
(0, node_test_1.default)("rollout: rollbackNow restores from backup", async () => {
    const ctx = await makeCtx();
    const live = (0, node_path_1.join)(ctx.resourcesPath, "spa");
    await node_fs_1.promises.mkdir(live, { recursive: true });
    await node_fs_1.promises.writeFile((0, node_path_1.join)(live, "index.html"), "<html>v1</html>");
    const stagedDir = (0, node_path_1.join)(ctx.userDataPath, "staged-update");
    await node_fs_1.promises.mkdir(stagedDir, { recursive: true });
    const tarPath = (0, node_path_1.join)(stagedDir, "spa.tar.gz");
    const sha = await makeTarball(tarPath, { "index.html": "<html>v2</html>" });
    const m = {
        ...VALID,
        tier2: { spa: { version: "0.2.1", url: "http://stubhost/spa.tar.gz", sha256: sha, size: 9999 } },
        tier3: undefined,
    };
    await node_fs_1.promises.writeFile((0, node_path_1.join)(stagedDir, "manifest.json"), JSON.stringify(m));
    const handle = (0, rollout_1.createRollout)(ctx, { setIntervalFn: (() => 0) });
    await handle.applyPending();
    strict_1.default.equal(await node_fs_1.promises.readFile((0, node_path_1.join)(ctx.resourcesPath, "spa", "index.html"), "utf8"), "<html>v2</html>");
    const r = await handle.rollbackNow();
    strict_1.default.deepEqual(r.rolled, ["spa"]);
    strict_1.default.equal(await node_fs_1.promises.readFile((0, node_path_1.join)(ctx.resourcesPath, "spa", "index.html"), "utf8"), "<html>v1</html>");
    await ctx.cleanup();
});
(0, node_test_1.default)("rollout: onStateChange emits transitions", async () => {
    const ctx = await makeCtx();
    const handle = (0, rollout_1.createRollout)(ctx, { setIntervalFn: (() => 0) });
    const emitter = new node_events_1.EventEmitter();
    const seen = [];
    const off = handle.onStateChange((i) => {
        seen.push(i.state);
        emitter.emit("got", i);
    });
    // Manually transition to test emitter.
    // checkNow will move idle -> checking -> update_available
    const origFetch = globalThis.fetch;
    globalThis.fetch = (async () => ({ ok: true, status: 200, text: async () => JSON.stringify(VALID), arrayBuffer: async () => new ArrayBuffer(0), headers: new Map() }));
    try {
        await handle.checkNow();
        strict_1.default.ok(seen.includes("checking"));
        strict_1.default.ok(seen.includes("update_available"));
    }
    finally {
        globalThis.fetch = origFetch;
        off();
        await ctx.cleanup();
    }
});
//# sourceMappingURL=rollout.test.js.map