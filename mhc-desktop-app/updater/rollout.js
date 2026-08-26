"use strict";
/**
 * Rollout orchestrator — wires manifest fetch, download, apply into a
 * single state machine the rest of the app subscribes to.
 *
 * Lifecycle:
 *   1. ``init(ctx, deps)`` — wires context (resourcesPath, userData,
 *      current versions). Idempotent.
 *   2. ``startBackgroundLoop()`` — schedules periodic manifest checks.
 *      Also called once on init. Never blocks the caller.
 *   3. ``checkNow()`` — user-triggered check (button in Settings).
 *   4. ``installAvailable()`` — user said "yes, install"; downloads
 *      and stages. Does NOT apply yet — apply happens at next launch
 *      (Tier 2) or via ``reloadBackend()`` (Tier 3).
 *   5. ``applyPending()`` — id called by main.ts at boot, BEFORE the
 *      window paints. Replaces staged payloads into ``resourcesPath``
 *      atomically, updates ``last-good.json``.
 *   6. ``commitIfHealthy()`` — called after backend /ready answers
 *      within ``ROLLBACK_GRACE_MS``. Writes last-good.json with the
 *      new versions. If ``/ready`` times out, triggers ``rollback()``.
 *
 * Notifications: every state transition calls ``deps.onState(info)``
 * so the tray / settings UI can react. The tray in main.ts turns
 * ``update_available`` -> a notification, ``staged`` -> "Restart now?".
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.DEFAULT_PREFS = exports.DownloadError = exports.ManifestError = void 0;
exports.createRollout = createRollout;
exports.readLastGood = readLastGood;
exports.mergePrefsFromFile = mergePrefsFromFile;
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
const state_1 = require("./state");
const log_1 = require("./log");
const prefs_1 = require("./prefs");
Object.defineProperty(exports, "DEFAULT_PREFS", { enumerable: true, get: function () { return prefs_1.DEFAULT_PREFS; } });
// ---------- internal state ----------
class Rollout {
    ctx;
    deps;
    info = state_1.INITIAL_INFO;
    lastManifest = null;
    checkTimer = null;
    running = false;
    emitter = new node_events_1.EventEmitter();
    constructor(ctx, deps = {}) {
        this.ctx = ctx;
        const sleep = deps.sleep ?? ((ms) => new Promise((r) => setTimeout(r, ms)));
        this.deps = {
            logger: deps.logger ?? (0, log_1.createUpdaterLogger)(ctx.userDataPath),
            sleep,
            setIntervalFn: deps.setIntervalFn ?? ((cb, ms) => setInterval(cb, ms)),
            clearIntervalFn: deps.clearIntervalFn ?? ((h) => clearInterval(h)),
            setTimeoutFn: deps.setTimeoutFn ?? ((cb, ms) => setTimeout(cb, ms)),
            clearTimeoutFn: deps.clearTimeoutFn ?? ((h) => clearTimeout(h)),
        };
        if (deps.onState)
            this.deps.onState = deps.onState;
    }
    // ---------- public API ----------
    getInfo() {
        return this.info;
    }
    getLastManifest() {
        return this.lastManifest;
    }
    onStateChange(cb) {
        this.emitter.on("state", cb);
        return () => this.emitter.off("state", cb);
    }
    setPrefs(p) {
        this.ctx.prefs = { ...this.ctx.prefs, ...p };
        // Caller persists to electron-store; we just react.
        return Promise.resolve();
    }
    /** Start the periodic check loop. Runs one immediate check, then
     *  every ``checkIntervalMs``. */
    startBackgroundLoop() {
        if (this.running)
            return;
        this.running = true;
        void this.checkNow().catch((e) => this.deps.logger.error(`initial check failed: ${e.message}`));
        const ms = this.ctx.checkIntervalMs ?? this.ctx.prefs.checkIntervalMs;
        this.checkTimer = this.deps.setIntervalFn(() => {
            void this.checkNow().catch((e) => this.deps.logger.error(`scheduled check failed: ${e.message}`));
        }, ms);
    }
    async checkNow() {
        if (!this.ctx.prefs.autoUpdate && !this.forcedCheck) {
            this.deps.logger.info("autoUpdate disabled — skipping check");
            return this.info;
        }
        this.forcedCheck = false;
        this.transition("checking");
        try {
            const manifestUrl = this.manifestUrl();
            const mirrors = this.ctx.mirrors ?? [];
            const { manifest, source } = await (0, manifest_1.fetchManifestWithMirrors)(manifestUrl, mirrors, {
                timeoutMs: 8000,
            });
            this.lastManifest = manifest;
            this.deps.logger.info(`manifest fetched from ${source} (released_at=${manifest.released_at}, channel=${manifest.channel})`);
            const available = (0, manifest_1.diffManifest)(manifest, this.ctx.current);
            if (available.forceTier1) {
                this.deps.logger.warn(`app ${this.ctx.appVersion} < min ${manifest.min_app_version} — Tier 1 required`);
                this.setInfo({
                    state: "update_available",
                    releasedAt: manifest.released_at,
                    available: {},
                    forceTier1: true,
                    channel: manifest.channel,
                });
                return this.info;
            }
            const hasAny = available.spa || available.content_packs || available.backend;
            if (!hasAny) {
                this.deps.logger.info("no updates available");
                this.setInfo({ state: "idle", releasedAt: manifest.released_at, channel: manifest.channel });
                return this.info;
            }
            this.deps.logger.info(`updates available: ${Object.keys(available)
                .filter((k) => k !== "forceTier1")
                .join(", ")}`);
            this.setInfo({
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
            this.deps.logger.warn(`check failed: ${msg}`);
            this.setInfo({ state: "download_failed", error: msg });
        }
        return this.info;
    }
    forcedCheck = false;
    async forceCheckNow() {
        this.forcedCheck = true;
        return this.checkNow();
    }
    async stageAvailable(updates) {
        if (!this.lastManifest) {
            throw new Error("stageAvailable called before checkNow — no manifest in hand");
        }
        const u = updates ??
            (0, manifest_1.diffManifest)(this.lastManifest, this.ctx.current);
        if (!u.spa && !u.content_packs && !u.backend) {
            this.deps.logger.info("stageAvailable: nothing to download");
            return this.info;
        }
        if (!this.ctx.prefs.autoUpdate && !this.forcedCheck) {
            this.deps.logger.info("autoUpdate disabled — refusing to stage");
            this.setInfo({ state: "idle", error: "auto-update disabled" });
            return this.info;
        }
        this.transition("downloading");
        const staged = await this.downloadAll(u);
        // Persist the manifest snapshot we staged against — that's what
        // ``applyPending()`` reads at next boot.
        const stagedDir = (0, node_path_1.join)(this.ctx.userDataPath, prefs_1.STAGED_DIR);
        await node_fs_1.promises.mkdir(stagedDir, { recursive: true });
        await node_fs_1.promises.writeFile((0, node_path_1.join)(stagedDir, prefs_1.STAGED_MANIFEST_FILENAME), JSON.stringify(this.lastManifest, null, 2), "utf8");
        this.setInfo({
            state: "staged",
            releasedAt: this.lastManifest.released_at,
            available: {
                spa: u.spa?.version ?? this.info.available?.spa,
                content_packs: u.content_packs?.version ?? this.info.available?.content_packs,
                backend: u.backend?.version ?? this.info.available?.backend,
            },
            channel: this.lastManifest.channel,
        });
        this.deps.logger.info(`staged: ${staged.join(", ")}`);
        return this.info;
    }
    async installAvailable() {
        return this.stageAvailable();
    }
    async applyPending() {
        if (!(0, node_fs_1.existsSync)(this.stagedManifestPath())) {
            this.deps.logger.info("applyPending: no staged manifest — nothing to do");
            return { applied: [] };
        }
        // If we don't have a manifest in hand (e.g. applyPending is the
        // first method called after a fresh install), re-read from disk.
        // safeCollectStagedEntries handles corruption gracefully.
        if (!this.lastManifest) {
            await this.safeCollectStagedEntries();
        }
        this.transition("applying");
        const entries = await this.collectStagedEntries();
        if (entries.length === 0) {
            this.deps.logger.warn("applyPending: staged manifest had no recognized payloads");
            this.transition("committed");
            await (0, applier_1.cleanStagedPayload)(this.ctx.userDataPath);
            return { applied: [] };
        }
        try {
            const res = await (0, applier_1.applyPayloads)({ resourcesPath: this.ctx.resourcesPath, userDataPath: this.ctx.userDataPath }, entries);
            this.deps.logger.info(`applied: ${res.applied.join(", ")}; backups: ${Object.entries(res.backups)
                .filter(([, v]) => v)
                .map(([k]) => k)
                .join(", ")}`);
            // Build the new versions map from the manifest we applied. We
            // deliberately don't ask applyPayloads() for it — the manifest
            // is the source of truth for "what did we just install?".
            const appliedVersions = {};
            const t2 = this.lastManifest?.tier2;
            const t3 = this.lastManifest?.tier3;
            if (res.applied.includes("spa") && t2?.spa)
                appliedVersions.spa = t2.spa.version;
            if (res.applied.includes("content-packs") && t2?.content_packs)
                appliedVersions["content-packs"] = t2.content_packs.version;
            if (res.applied.includes("backend") && t3?.backend)
                appliedVersions.backend = t3.backend.version;
            // Don't clean staged yet — we may need to rollback if the new
            // backend fails /ready within the grace window.
            this.setInfo({
                state: "committed",
                available: appliedVersions,
                channel: this.info.channel,
            });
            return { applied: res.applied };
        }
        catch (e) {
            const msg = e instanceof Error ? e.message : String(e);
            this.deps.logger.error(`apply failed: ${msg}`);
            const { rolled } = await (0, applier_1.rollback)({ resourcesPath: this.ctx.resourcesPath, userDataPath: this.ctx.userDataPath }, entries.map((e) => e.key));
            this.setInfo({ state: "rolled_back", error: msg });
            this.deps.logger.warn(`rolled back: ${rolled.join(", ")}`);
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
        this.transition("idle");
        this.deps.logger.info(`committed last-good: ${JSON.stringify(info.versions)}`);
    }
    async rollbackNow() {
        const stagedEntries = await this.safeCollectStagedEntries();
        if (stagedEntries.length === 0) {
            this.deps.logger.warn("rollbackNow: nothing staged to roll back");
            return { rolled: [] };
        }
        const { rolled } = await (0, applier_1.rollback)({ resourcesPath: this.ctx.resourcesPath, userDataPath: this.ctx.userDataPath }, stagedEntries.map((e) => e.key));
        await (0, applier_1.cleanStagedPayload)(this.ctx.userDataPath);
        this.setInfo({ state: "rolled_back", error: "manual rollback" });
        return { rolled };
    }
    dispose() {
        if (this.checkTimer) {
            this.deps.clearIntervalFn(this.checkTimer);
            this.checkTimer = null;
        }
        this.running = false;
    }
    // ---------- internals ----------
    manifestUrl() {
        return this.ctx.prefs.manifestUrl || this.ctx.defaultManifestUrl;
    }
    stagedManifestPath() {
        return (0, node_path_1.join)(this.ctx.userDataPath, prefs_1.STAGED_DIR, prefs_1.STAGED_MANIFEST_FILENAME);
    }
    async collectStagedEntries() {
        const dir = (0, node_path_1.join)(this.ctx.userDataPath, prefs_1.STAGED_DIR);
        const entries = [];
        if (this.lastManifest?.tier2?.spa) {
            const p = (0, node_path_1.join)(dir, "spa.tar.gz");
            if ((0, node_fs_1.existsSync)(p))
                entries.push({ key: "spa", tarball: p, sha256: this.lastManifest.tier2.spa.sha256 });
        }
        if (this.lastManifest?.tier2?.content_packs) {
            const p = (0, node_path_1.join)(dir, "content-packs.tar.gz");
            if ((0, node_fs_1.existsSync)(p))
                entries.push({
                    key: "content-packs",
                    tarball: p,
                    sha256: this.lastManifest.tier2.content_packs.sha256,
                });
        }
        if (this.lastManifest?.tier3?.backend) {
            const p = (0, node_path_1.join)(dir, "backend.tar.gz");
            if ((0, node_fs_1.existsSync)(p))
                entries.push({ key: "backend", tarball: p, sha256: this.lastManifest.tier3.backend.sha256 });
        }
        return entries;
    }
    async safeCollectStagedEntries() {
        try {
            const raw = await node_fs_1.promises.readFile(this.stagedManifestPath(), "utf8");
            const m = (0, manifest_1.parseManifest)(JSON.parse(raw));
            this.lastManifest = m;
            return this.collectStagedEntries();
        }
        catch {
            return [];
        }
    }
    async downloadAll(u) {
        const stagedDir = (0, node_path_1.join)(this.ctx.userDataPath, prefs_1.STAGED_DIR);
        await node_fs_1.promises.mkdir(stagedDir, { recursive: true });
        const staged = [];
        if (u.spa) {
            await this.downloadOne(u.spa, (0, node_path_1.join)(stagedDir, "spa.tar.gz"), "spa");
            staged.push("spa");
        }
        if (u.content_packs) {
            await this.downloadOne(u.content_packs, (0, node_path_1.join)(stagedDir, "content-packs.tar.gz"), "content-packs");
            staged.push("content-packs");
        }
        if (u.backend) {
            await this.downloadOne(u.backend, (0, node_path_1.join)(stagedDir, "backend.tar.gz"), "backend");
            staged.push("backend");
        }
        return staged;
    }
    async downloadOne(entry, dest, label) {
        this.deps.logger.info(`download start: ${label} ${entry.url} (${entry.size} bytes)`);
        try {
            const { bytes } = await (0, downloader_1.downloadToFile)(entry.url, dest, {
                expectedSha256: entry.sha256,
                contentLength: entry.size,
                onProgress: (n) => {
                    this.setInfo({
                        state: "downloading",
                        progressBytes: n,
                        progressTotal: entry.size,
                    });
                },
            });
            this.deps.logger.info(`download done: ${label} ${bytes} bytes`);
        }
        catch (e) {
            const msg = e instanceof Error ? e.message : String(e);
            this.deps.logger.error(`download failed: ${label} ${msg}`);
            this.setInfo({ state: "download_failed", error: `${label}: ${msg}` });
            throw e;
        }
    }
    transition(to) {
        const from = this.info.state;
        try {
            (0, state_1.assertTransition)(from, to);
        }
        catch (e) {
            this.deps.logger.warn(`illegal transition ${from} -> ${to}: ${e.message}`);
            // Best-effort: still update the info even if transition is
            // unusual — useful for tests that intentionally double-step.
        }
        this.setInfo({ ...this.info, state: to });
    }
    setInfo(next) {
        this.info = next;
        this.deps.logger.info(`state=${next.state}` + (next.error ? ` error=${next.error}` : ""));
        this.deps.onState?.(next);
        this.emitter.emit("state", next);
    }
}
// ---------- factory ----------
function createRollout(ctx, deps = {}) {
    return new Rollout(ctx, deps);
}
// ---------- helpers exported for main.ts ----------
/** Read ``last-good.json`` from ``userData``; returns an empty record
 *  when missing/corrupt (so a first boot doesn't crash). */
async function readLastGood(userDataPath) {
    try {
        const raw = await node_fs_1.promises.readFile((0, node_path_1.join)(userDataPath, prefs_1.LAST_GOOD_FILENAME), "utf8");
        return JSON.parse(raw);
    }
    catch {
        return null;
    }
}
/** Read prefs from the on-disk prefs file. The shape accepts both
 *  electron-store's defaults and the updater-namespaced version. */
function mergePrefsFromFile(file) {
    return (0, prefs_1.readUpdaterPrefsFromFile)(file ?? {});
}
/** Build a ``CurrentVersions`` snapshot at boot. Used by main.ts to
 *  pass to the rollout context. */
function currentVersionsFromLastGood(appVersion, lastGood) {
    if (!lastGood) {
        return { app: appVersion };
    }
    return {
        app: lastGood.app ?? appVersion,
        spa: lastGood.spa,
        content_packs: lastGood.content_packs,
        backend: lastGood.backend,
    };
}
/** First-boot empty last-good writer; used when no previous install
 *  exists. */
async function writeEmptyLastGood(userDataPath, appVersion) {
    const lg = (0, prefs_1.emptyLastGood)(appVersion);
    await node_fs_1.promises.writeFile((0, node_path_1.join)(userDataPath, prefs_1.LAST_GOOD_FILENAME), JSON.stringify(lg, null, 2), "utf8");
}
/** Helper: detect if a staged manifest exists. main.ts uses this to
 *  decide whether to call ``applyPending()`` early in bootstrap. */
function hasStagedManifest(userDataPath) {
    return (0, node_fs_1.existsSync)((0, node_path_1.join)(userDataPath, prefs_1.STAGED_DIR, prefs_1.STAGED_MANIFEST_FILENAME));
}
//# sourceMappingURL=rollout.js.map