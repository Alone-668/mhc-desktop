"use strict";
/**
 * Rollout orchestrator — wires manifest fetch, download, apply into
 * a single state machine the rest of the app subscribes to.
 *
 * See ``docs/UPDATE-MECHANISM.md`` §4 for the canonical state diagram.
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.DEFAULT_PREFS = exports.DownloadError = exports.ManifestError = void 0;
exports.createRollout = createRollout;
exports.readLastGood = readLastGood;
exports.currentVersionsFromLastGood = currentVersionsFromLastGood;
exports.writeEmptyLastGood = writeEmptyLastGood;
exports.hasStagedManifest = hasStagedManifest;
const node_events_1 = require("node:events");
const node_fs_1 = require("node:fs");
const node_path_1 = require("node:path");
const manifest_1 = require("./manifest");
Object.defineProperty(exports, "ManifestError", { enumerable: true, get: function () { return manifest_1.ManifestError; } });
const downloader_1 = require("./downloader");
Object.defineProperty(exports, "DownloadError", { enumerable: true, get: function () { return downloader_1.DownloadError; } });
const applier_1 = require("./applier");
const log_1 = require("./log");
const prefs_1 = require("./prefs");
Object.defineProperty(exports, "DEFAULT_PREFS", { enumerable: true, get: function () { return prefs_1.DEFAULT_PREFS; } });
class Rollout {
    ctx;
    logger;
    onState;
    info = { state: "idle" };
    lastManifest = null;
    checkTimer = null;
    running = false;
    emitter = new node_events_1.EventEmitter();
    constructor(ctx, deps = {}) {
        this.ctx = ctx;
        this.logger = deps.logger ?? (0, log_1.createUpdaterLogger)(ctx.userDataPath);
        this.onState = deps.onState;
    }
    // ---------- public API ----------
    getInfo() { return this.info; }
    getLastManifest() { return this.lastManifest; }
    onStateChange(cb) {
        this.emitter.on("state", cb);
        return () => this.emitter.off("state", cb);
    }
    setPrefs(p) {
        this.ctx.prefs = { ...this.ctx.prefs, ...p };
        return Promise.resolve();
    }
    startBackgroundLoop() {
        if (this.running)
            return;
        this.running = true;
        void this.checkNow().catch((e) => this.logger.error(`initial check failed: ${e.message}`));
        const ms = this.ctx.checkIntervalMs ?? this.ctx.prefs.checkIntervalMs;
        this.checkTimer = setInterval(() => {
            void this.checkNow().catch((e) => this.logger.error(`scheduled check failed: ${e.message}`));
        }, ms);
    }
    async checkNow() {
        if (!this.ctx.prefs.autoUpdate) {
            this.logger.info("autoUpdate disabled — skipping check");
            return this.info;
        }
        this.setInfo({ ...this.info, state: "checking" });
        try {
            const { manifest, source } = await (0, manifest_1.fetchManifestWithMirrors)(this.manifestUrl(), this.ctx.mirrors ?? [], { timeoutMs: 8000 });
            this.lastManifest = manifest;
            this.logger.info(`manifest fetched from ${source} (released_at=${manifest.released_at}, channel=${manifest.channel})`);
            const available = (0, manifest_1.diffManifest)(manifest, this.ctx.current);
            if (available.forceTier1) {
                this.logger.warn(`app ${this.ctx.appVersion} < min ${manifest.min_app_version} — Tier 1 required`);
                return this.setInfo({
                    ...this.info,
                    state: "update_available",
                    releasedAt: manifest.released_at,
                    available: {},
                    forceTier1: true,
                    channel: manifest.channel,
                });
            }
            const hasAny = available.spa || available.content_packs || available.backend;
            if (!hasAny) {
                this.logger.info("no updates available");
                return this.setInfo({
                    ...this.info,
                    state: "idle",
                    releasedAt: manifest.released_at,
                    channel: manifest.channel,
                });
            }
            this.logger.info(`updates available: ${Object.keys(available).filter((k) => k !== "forceTier1").join(", ")}`);
            return this.setInfo({
                ...this.info,
                state: "update_available",
                releasedAt: manifest.released_at,
                available: {
                    spa: available.spa?.version,
                    content_packs: available.content_packs?.version,
                    backend: available.backend?.version,
                },
                channel: manifest.channel,
            });
        }
        catch (e) {
            const msg = e instanceof Error ? e.message : String(e);
            this.logger.warn(`check failed: ${msg}`);
            return this.setInfo({ ...this.info, state: "download_failed", error: msg });
        }
    }
    async stageAvailable(updates) {
        if (!this.lastManifest)
            throw new Error("stageAvailable called before checkNow");
        const u = updates ?? (0, manifest_1.diffManifest)(this.lastManifest, this.ctx.current);
        if (!u.spa && !u.content_packs && !u.backend) {
            this.logger.info("stageAvailable: nothing to download");
            return this.info;
        }
        if (!this.ctx.prefs.autoUpdate) {
            this.logger.info("autoUpdate disabled — refusing to stage");
            return this.setInfo({ ...this.info, state: "idle", error: "auto-update disabled" });
        }
        this.setInfo({ ...this.info, state: "downloading" });
        const staged = await this.downloadAll(u);
        const stagedDir = (0, node_path_1.join)(this.ctx.userDataPath, prefs_1.STAGED_DIR);
        await node_fs_1.promises.mkdir(stagedDir, { recursive: true });
        await node_fs_1.promises.writeFile((0, node_path_1.join)(stagedDir, prefs_1.STAGED_MANIFEST_FILENAME), JSON.stringify(this.lastManifest, null, 2), "utf8");
        this.logger.info(`staged: ${staged.join(", ")}`);
        return this.setInfo({
            ...this.info,
            state: "staged",
            releasedAt: this.lastManifest.released_at,
            available: {
                spa: u.spa?.version ?? this.info.available?.spa,
                content_packs: u.content_packs?.version ?? this.info.available?.content_packs,
                backend: u.backend?.version ?? this.info.available?.backend,
            },
            channel: this.lastManifest.channel,
        });
    }
    installAvailable() {
        return this.stageAvailable();
    }
    async applyPending() {
        if (!(0, node_fs_1.existsSync)(this.stagedManifestPath())) {
            this.logger.info("applyPending: no staged manifest — nothing to do");
            return { applied: [] };
        }
        // First-call path (no manifest in memory yet): re-read from disk.
        if (!this.lastManifest)
            await this.reloadStagedManifest();
        this.setInfo({ ...this.info, state: "applying" });
        const entries = this.collectStagedEntries();
        if (entries.length === 0) {
            this.logger.warn("applyPending: staged manifest had no recognized payloads");
            this.setInfo({ ...this.info, state: "committed" });
            await (0, applier_1.cleanStagedPayload)(this.ctx.userDataPath);
            return { applied: [] };
        }
        try {
            const res = await (0, applier_1.applyPayloads)({ resourcesPath: this.ctx.resourcesPath, userDataPath: this.ctx.userDataPath }, entries);
            this.logger.info(`applied: ${res.applied.join(", ")}; backups: ${Object.entries(res.backups)
                .filter(([, v]) => v).map(([k]) => k).join(", ")}`);
            const appliedVersions = this.appliedVersionsFrom(res.applied);
            // Update ctx.current so a follow-up checkNow doesn't immediately
            // re-flag the just-installed version as available again. Cleanup
            // of staged payload happens in commitIfHealthy (post /ready).
            this.ctx.current = {
                app: this.ctx.appVersion,
                spa: appliedVersions.spa ?? this.ctx.current.spa,
                content_packs: appliedVersions["content-packs"] ?? this.ctx.current.content_packs,
                backend: appliedVersions.backend ?? this.ctx.current.backend,
            };
            this.setInfo({ ...this.info, state: "committed", available: appliedVersions });
            return { applied: res.applied };
        }
        catch (e) {
            const msg = e instanceof Error ? e.message : String(e);
            this.logger.error(`apply failed: ${msg}`);
            const { rolled } = await (0, applier_1.rollback)({ resourcesPath: this.ctx.resourcesPath, userDataPath: this.ctx.userDataPath }, entries.map((e) => e.key));
            this.setInfo({ ...this.info, state: "rolled_back", error: msg });
            this.logger.warn(`rolled back: ${rolled.join(", ")}`);
            return { applied: [] };
        }
    }
    async commitIfHealthy(info) {
        if (this.info.state !== "committed")
            return;
        const lg = (0, prefs_1.makeLastGood)({
            app: this.ctx.appVersion,
            spa: info.versions.spa ?? this.ctx.current.spa,
            content_packs: info.versions.content_packs ?? this.ctx.current.content_packs,
            backend: info.versions.backend ?? this.ctx.current.backend,
        });
        await node_fs_1.promises.writeFile((0, node_path_1.join)(this.ctx.userDataPath, prefs_1.LAST_GOOD_FILENAME), JSON.stringify(lg, null, 2), "utf8");
        this.ctx.current = {
            app: this.ctx.appVersion,
            spa: lg.spa,
            content_packs: lg.content_packs,
            backend: lg.backend,
        };
        await (0, applier_1.cleanStagedPayload)(this.ctx.userDataPath);
        this.logger.info(`committed last-good: ${JSON.stringify(info.versions)}`);
        this.setInfo({ ...this.info, state: "idle" });
    }
    async rollbackNow() {
        if (!this.lastManifest)
            await this.reloadStagedManifest();
        const entries = this.collectStagedEntries();
        if (entries.length === 0) {
            this.logger.warn("rollbackNow: nothing staged to roll back");
            return { rolled: [] };
        }
        const { rolled } = await (0, applier_1.rollback)({ resourcesPath: this.ctx.resourcesPath, userDataPath: this.ctx.userDataPath }, entries.map((e) => e.key));
        await (0, applier_1.cleanStagedPayload)(this.ctx.userDataPath);
        this.setInfo({ ...this.info, state: "rolled_back", error: "manual rollback" });
        return { rolled };
    }
    dispose() {
        if (this.checkTimer)
            clearInterval(this.checkTimer);
        this.checkTimer = null;
        this.running = false;
    }
    // ---------- internals ----------
    manifestUrl() {
        return this.ctx.prefs.manifestUrl || this.ctx.defaultManifestUrl;
    }
    stagedManifestPath() {
        return (0, node_path_1.join)(this.ctx.userDataPath, prefs_1.STAGED_DIR, prefs_1.STAGED_MANIFEST_FILENAME);
    }
    /** Re-read the staged manifest from disk and stash it as lastManifest.
     *  Returns silently on corruption — the caller's collectStagedEntries
     *  will then produce an empty list and apply becomes a no-op. */
    async reloadStagedManifest() {
        try {
            this.lastManifest = (0, manifest_1.parseManifest)(JSON.parse(await node_fs_1.promises.readFile(this.stagedManifestPath(), "utf8")));
        }
        catch {
            this.lastManifest = null;
        }
    }
    collectStagedEntries() {
        const dir = (0, node_path_1.join)(this.ctx.userDataPath, prefs_1.STAGED_DIR);
        const entries = [];
        const t2 = this.lastManifest?.tier2;
        const t3 = this.lastManifest?.tier3;
        if (t2?.spa && (0, node_fs_1.existsSync)((0, node_path_1.join)(dir, "spa.tar.gz"))) {
            entries.push({ key: "spa", tarball: (0, node_path_1.join)(dir, "spa.tar.gz"), sha256: t2.spa.sha256 });
        }
        if (t2?.content_packs && (0, node_fs_1.existsSync)((0, node_path_1.join)(dir, "content-packs.tar.gz"))) {
            entries.push({
                key: "content-packs",
                tarball: (0, node_path_1.join)(dir, "content-packs.tar.gz"),
                sha256: t2.content_packs.sha256,
            });
        }
        if (t3?.backend && (0, node_fs_1.existsSync)((0, node_path_1.join)(dir, "backend.tar.gz"))) {
            entries.push({ key: "backend", tarball: (0, node_path_1.join)(dir, "backend.tar.gz"), sha256: t3.backend.sha256 });
        }
        return entries;
    }
    appliedVersionsFrom(applied) {
        const t2 = this.lastManifest?.tier2;
        const t3 = this.lastManifest?.tier3;
        const v = {};
        if (applied.includes("spa") && t2?.spa)
            v.spa = t2.spa.version;
        if (applied.includes("content-packs") && t2?.content_packs)
            v["content-packs"] = t2.content_packs.version;
        if (applied.includes("backend") && t3?.backend)
            v.backend = t3.backend.version;
        return v;
    }
    async downloadAll(u) {
        const stagedDir = (0, node_path_1.join)(this.ctx.userDataPath, prefs_1.STAGED_DIR);
        await node_fs_1.promises.mkdir(stagedDir, { recursive: true });
        const staged = [];
        for (const [key, entry] of [
            ["spa", u.spa],
            ["content-packs", u.content_packs],
            ["backend", u.backend],
        ]) {
            if (!entry)
                continue;
            await this.downloadOne(entry, (0, node_path_1.join)(stagedDir, `${key}.tar.gz`), key);
            staged.push(key);
        }
        return staged;
    }
    async downloadOne(entry, dest, label) {
        this.logger.info(`download start: ${label} ${entry.url} (${entry.size} bytes)`);
        try {
            const { bytes } = await (0, downloader_1.downloadToFile)(entry.url, dest, {
                expectedSha256: entry.sha256,
                contentLength: entry.size,
                onProgress: (n) => this.setInfo({ ...this.info, progressBytes: n, progressTotal: entry.size }),
            });
            this.logger.info(`download done: ${label} ${bytes} bytes`);
        }
        catch (e) {
            const msg = e instanceof Error ? e.message : String(e);
            this.logger.error(`download failed: ${label} ${msg}`);
            this.setInfo({ ...this.info, state: "download_failed", error: `${label}: ${msg}` });
            throw e;
        }
    }
    setInfo(next) {
        this.info = next;
        this.logger.info(`state=${next.state}` + (next.error ? ` error=${next.error}` : ""));
        this.onState?.(next);
        this.emitter.emit("state", next);
        return next;
    }
}
function createRollout(ctx, deps = {}) {
    return new Rollout(ctx, deps);
}
// ---------- helpers exported for main.ts / index.ts ----------
async function readLastGood(userDataPath) {
    try {
        return JSON.parse(await node_fs_1.promises.readFile((0, node_path_1.join)(userDataPath, prefs_1.LAST_GOOD_FILENAME), "utf8"));
    }
    catch {
        return null;
    }
}
function currentVersionsFromLastGood(appVersion, lastGood) {
    if (!lastGood)
        return { app: appVersion };
    return {
        app: lastGood.app ?? appVersion,
        spa: lastGood.spa,
        content_packs: lastGood.content_packs,
        backend: lastGood.backend,
    };
}
async function writeEmptyLastGood(userDataPath, appVersion) {
    const lg = (0, prefs_1.makeLastGood)({ app: appVersion });
    await node_fs_1.promises.writeFile((0, node_path_1.join)(userDataPath, prefs_1.LAST_GOOD_FILENAME), JSON.stringify(lg, null, 2), "utf8");
}
function hasStagedManifest(userDataPath) {
    return (0, node_fs_1.existsSync)((0, node_path_1.join)(userDataPath, prefs_1.STAGED_DIR, prefs_1.STAGED_MANIFEST_FILENAME));
}
//# sourceMappingURL=rollout.js.map