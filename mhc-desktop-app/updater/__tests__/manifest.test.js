"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
const node_test_1 = __importDefault(require("node:test"));
const strict_1 = __importDefault(require("node:assert/strict"));
const manifest_1 = require("../manifest");
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
        backend: { version: "0.2.1", url: "https://cdn/be.tgz", sha256: "c".repeat(64), size: 300, python_tag: "20250814-x86_64-pc-windows-msvc-shared-install_only" },
    },
    release_notes: "hello",
};
(0, node_test_1.default)("parseManifest: accepts a complete manifest", () => {
    const m = (0, manifest_1.parseManifest)(VALID);
    strict_1.default.equal(m.manifest_version, 1);
    strict_1.default.equal(m.tier2?.spa?.version, "0.2.1");
});
(0, node_test_1.default)("parseManifest: rejects non-objects", () => {
    strict_1.default.throws(() => (0, manifest_1.parseManifest)("nope"), manifest_1.ManifestError);
    strict_1.default.throws(() => (0, manifest_1.parseManifest)(null), manifest_1.ManifestError);
});
(0, node_test_1.default)("parseManifest: rejects unknown manifest_version", () => {
    strict_1.default.throws(() => (0, manifest_1.parseManifest)({ ...VALID, manifest_version: 99 }), /unsupported manifest_version=99/);
});
(0, node_test_1.default)("parseManifest: rejects invalid channel", () => {
    strict_1.default.throws(() => (0, manifest_1.parseManifest)({ ...VALID, channel: "rc" }), /invalid channel=rc/);
});
(0, node_test_1.default)("parseManifest: rejects tier entries missing fields", () => {
    strict_1.default.throws(() => (0, manifest_1.parseManifest)({ ...VALID, tier2: { spa: { version: "x", url: "u" } } }), /tier2.spa.sha256 missing/);
});
(0, node_test_1.default)("parseManifest: tier2/tier3 fully optional", () => {
    const minimal = {
        manifest_version: 1,
        channel: "stable",
        released_at: "2026-01-01T00:00:00Z",
        min_app_version: "0.0.1",
    };
    const m = (0, manifest_1.parseManifest)(minimal);
    strict_1.default.equal(m.tier2, undefined);
    strict_1.default.equal(m.tier3, undefined);
});
(0, node_test_1.default)("compareVersions: numeric semver", () => {
    strict_1.default.equal((0, manifest_1.compareVersions)("0.1.0", "0.2.0") < 0, true);
    strict_1.default.equal((0, manifest_1.compareVersions)("0.2.0", "0.2.0"), 0);
    strict_1.default.equal((0, manifest_1.compareVersions)("1.0.0", "0.99.99") > 0, true);
});
(0, node_test_1.default)("compareVersions: date-shaped versions", () => {
    strict_1.default.equal((0, manifest_1.compareVersions)("2026-09-01", "2026-09-15") < 0, true);
    strict_1.default.equal((0, manifest_1.compareVersions)("2026-09-15", "2026-09-15"), 0);
});
(0, node_test_1.default)("compareVersions: trailing zero segments are equal", () => {
    // Semver treats "0.1" and "0.1.0" as equivalent; neither is "longer wins".
    strict_1.default.equal((0, manifest_1.compareVersions)("0.1", "0.1.0"), 0);
    strict_1.default.equal((0, manifest_1.compareVersions)("0.1.0", "0.1"), 0);
    strict_1.default.equal((0, manifest_1.compareVersions)("0.2.1", "0.2.1.1") < 0, true);
    strict_1.default.equal((0, manifest_1.compareVersions)("0.2.1.1", "0.2.1") > 0, true);
});
(0, node_test_1.default)("diffManifest: app below min_app_version triggers forceTier1", () => {
    const out = (0, manifest_1.diffManifest)(VALID, { app: "0.0.5" });
    strict_1.default.equal(out.forceTier1, true);
});
(0, node_test_1.default)("diffManifest: app at min_app_version does not force Tier 1", () => {
    const out = (0, manifest_1.diffManifest)(VALID, { app: "0.1.0" });
    strict_1.default.equal(out.forceTier1, false);
});
(0, node_test_1.default)("diffManifest: marks newer components as available", () => {
    // current spa 0.2.0 < manifest spa 0.2.1 -> available
    // current backend 0.2.1 == manifest backend 0.2.1 -> not available
    // current content_packs undefined < 2026-09-15 -> available
    const out = (0, manifest_1.diffManifest)(VALID, { app: "0.1.0", spa: "0.2.0", backend: "0.2.1" });
    strict_1.default.ok(out.spa);
    strict_1.default.equal(out.spa?.version, "0.2.1");
    strict_1.default.equal(out.backend, undefined);
    strict_1.default.ok(out.content_packs);
});
(0, node_test_1.default)("diffManifest: returns everything when current is empty", () => {
    const out = (0, manifest_1.diffManifest)(VALID, { app: "0.1.0" });
    strict_1.default.ok(out.spa);
    strict_1.default.ok(out.content_packs);
    strict_1.default.ok(out.backend);
});
(0, node_test_1.default)("fetchManifestWithMirrors: returns first successful source", async () => {
    const fakeOk = async () => ({
        ok: true,
        status: 200,
        text: async () => JSON.stringify(VALID),
        arrayBuffer: async () => new ArrayBuffer(0),
    });
    const fakeFail = async () => ({
        ok: false,
        status: 503,
        text: async () => "",
        arrayBuffer: async () => new ArrayBuffer(0),
    });
    const { manifest, source } = await (0, manifest_1.fetchManifestWithMirrors)("https://primary.example.com/update.json", ["https://mirror-a.example.com", "https://mirror-b.example.com"], {
        fetcher: async (url) => {
            if (url.includes("primary"))
                return fakeOk();
            return fakeFail();
        },
    });
    strict_1.default.equal(manifest.tier2?.spa?.version, "0.2.1");
    strict_1.default.equal(source, "https://primary.example.com/update.json");
});
(0, node_test_1.default)("fetchManifestWithMirrors: falls back to first mirror when primary fails", async () => {
    const calls = [];
    const { manifest, source } = await (0, manifest_1.fetchManifestWithMirrors)("https://primary.example.com/update.json", ["https://mirror-a.example.com", "https://mirror-b.example.com"], {
        fetcher: async (url) => {
            calls.push(url);
            if (url.includes("primary")) {
                return { ok: false, status: 404, text: async () => "", arrayBuffer: async () => new ArrayBuffer(0) };
            }
            if (url.includes("mirror-a")) {
                return { ok: false, status: 500, text: async () => "", arrayBuffer: async () => new ArrayBuffer(0) };
            }
            return { ok: true, status: 200, text: async () => JSON.stringify(VALID), arrayBuffer: async () => new ArrayBuffer(0) };
        },
    });
    strict_1.default.equal(manifest.min_app_version, "0.1.0");
    strict_1.default.ok(source.includes("mirror-b"));
    strict_1.default.equal(calls.length, 3);
});
(0, node_test_1.default)("fetchManifestWithMirrors: throws when all fail", async () => {
    await strict_1.default.rejects((0, manifest_1.fetchManifestWithMirrors)("https://primary.example.com/update.json", [], {
        fetcher: async () => ({ ok: false, status: 500, text: async () => "", arrayBuffer: async () => new ArrayBuffer(0) }),
    }), /all manifest sources failed/);
});
//# sourceMappingURL=manifest.test.js.map