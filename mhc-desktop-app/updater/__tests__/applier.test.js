"use strict";
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
const node_test_1 = __importDefault(require("node:test"));
const strict_1 = __importDefault(require("node:assert/strict"));
const node_fs_1 = require("node:fs");
const node_os_1 = require("node:os");
const node_path_1 = require("node:path");
const applier_1 = require("../applier");
/** Build a small fake payload: a directory with 3 files, tar+gzip it
 *  via the system tar (using createTarGz so tests avoid the raw-spawn
 *  argv quirks). Returns the path to the tarball + SHA. */
async function makeFakeTarball(payloadDir) {
    await node_fs_1.promises.mkdir(payloadDir, { recursive: true });
    await node_fs_1.promises.writeFile((0, node_path_1.join)(payloadDir, "index.html"), "<html>v2</html>");
    await node_fs_1.promises.mkdir((0, node_path_1.join)(payloadDir, "assets"), { recursive: true });
    await node_fs_1.promises.writeFile((0, node_path_1.join)(payloadDir, "assets", "main.js"), "console.log('v2')");
    await node_fs_1.promises.writeFile((0, node_path_1.join)(payloadDir, "brand.svg"), "<svg/>");
    const tarball = payloadDir + ".tar.gz";
    await (0, applier_1.createTarGz)(payloadDir, tarball);
    const sha256 = await (0, applier_1.sha256OfFile)(tarball);
    return { tarball, sha256 };
}
async function makeContext() {
    const root = await node_fs_1.promises.mkdtemp((0, node_path_1.join)((0, node_os_1.tmpdir)(), "mhc-upd-"));
    const resourcesPath = (0, node_path_1.join)(root, "resources");
    const userDataPath = (0, node_path_1.join)(root, "userData");
    await node_fs_1.promises.mkdir(resourcesPath, { recursive: true });
    await node_fs_1.promises.mkdir(userDataPath, { recursive: true });
    return {
        resourcesPath,
        userDataPath,
        cleanup: async () => node_fs_1.promises.rm(root, { recursive: true, force: true }),
    };
}
(0, node_test_1.default)("sha256OfFile computes the correct hash", async () => {
    const tmp = await node_fs_1.promises.mkdtemp((0, node_path_1.join)((0, node_os_1.tmpdir)(), "mhc-sha-"));
    try {
        const p = (0, node_path_1.join)(tmp, "f.bin");
        await node_fs_1.promises.writeFile(p, "hello");
        const expected = (await Promise.resolve().then(() => __importStar(require("node:crypto")))).createHash("sha256").update("hello").digest("hex");
        strict_1.default.equal(await (0, applier_1.sha256OfFile)(p), expected);
    }
    finally {
        await node_fs_1.promises.rm(tmp, { recursive: true, force: true });
    }
});
(0, node_test_1.default)("atomicReplace: rename within same volume", async () => {
    const tmp = await node_fs_1.promises.mkdtemp((0, node_path_1.join)((0, node_os_1.tmpdir)(), "mhc-atr-"));
    try {
        const src = (0, node_path_1.join)(tmp, "src");
        const dst = (0, node_path_1.join)(tmp, "dst");
        await node_fs_1.promises.mkdir(src);
        await node_fs_1.promises.writeFile((0, node_path_1.join)(src, "x"), "x");
        await (0, applier_1.atomicReplace)(src, dst);
        strict_1.default.equal(await node_fs_1.promises.readFile((0, node_path_1.join)(dst, "x"), "utf8"), "x");
    }
    finally {
        await node_fs_1.promises.rm(tmp, { recursive: true, force: true });
    }
});
(0, node_test_1.default)("extractTarGz round-trip", async () => {
    const tmp = await node_fs_1.promises.mkdtemp((0, node_path_1.join)((0, node_os_1.tmpdir)(), "mhc-tar-"));
    try {
        const src = (0, node_path_1.join)(tmp, "src");
        const { tarball } = await makeFakeTarball(src);
        const dest = (0, node_path_1.join)(tmp, "out");
        await (0, applier_1.extractTarGz)(tarball, dest);
        strict_1.default.equal(await node_fs_1.promises.readFile((0, node_path_1.join)(dest, "index.html"), "utf8"), "<html>v2</html>");
        strict_1.default.equal(await node_fs_1.promises.readFile((0, node_path_1.join)(dest, "assets", "main.js"), "utf8"), "console.log('v2')");
    }
    finally {
        await node_fs_1.promises.rm(tmp, { recursive: true, force: true });
    }
});
(0, node_test_1.default)("applyPayloads: extracts, swaps live aside, installs payload", async () => {
    const ctx = await makeContext();
    try {
        const live = (0, node_path_1.join)(ctx.resourcesPath, "spa");
        await node_fs_1.promises.mkdir(live, { recursive: true });
        await node_fs_1.promises.writeFile((0, node_path_1.join)(live, "index.html"), "<html>v1</html>");
        const stagingDir = (0, node_path_1.join)(ctx.userDataPath, "staged-update");
        await node_fs_1.promises.mkdir(stagingDir, { recursive: true });
        const payload = (0, node_path_1.join)(stagingDir, "v2-spa");
        const { tarball, sha256 } = await makeFakeTarball(payload);
        const tarballDest = (0, node_path_1.join)(stagingDir, "spa.tar.gz");
        await node_fs_1.promises.rename(tarball, tarballDest);
        const res = await (0, applier_1.applyPayloads)(ctx, [{ key: "spa", tarball: tarballDest, sha256 }]);
        strict_1.default.deepEqual(res.applied, ["spa"]);
        strict_1.default.equal(await node_fs_1.promises.readFile((0, node_path_1.join)(ctx.resourcesPath, "spa", "index.html"), "utf8"), "<html>v2</html>");
        strict_1.default.ok(res.backups.spa);
        const backup = res.backups.spa;
        strict_1.default.ok(backup.includes(".bak."));
        strict_1.default.equal(await node_fs_1.promises.readFile((0, node_path_1.join)(backup, "index.html"), "utf8"), "<html>v1</html>");
    }
    finally {
        await ctx.cleanup();
    }
});
(0, node_test_1.default)("applyPayloads: rejects when tarball sha mismatches manifest", async () => {
    const ctx = await makeContext();
    try {
        const stagingDir = (0, node_path_1.join)(ctx.userDataPath, "staged-update");
        await node_fs_1.promises.mkdir(stagingDir, { recursive: true });
        const payload = (0, node_path_1.join)(stagingDir, "v2-spa");
        const { tarball } = await makeFakeTarball(payload);
        const tarballDest = (0, node_path_1.join)(stagingDir, "spa.tar.gz");
        await node_fs_1.promises.rename(tarball, tarballDest);
        const wrongSha = "0".repeat(64);
        await strict_1.default.rejects((0, applier_1.applyPayloads)(ctx, [{ key: "spa", tarball: tarballDest, sha256: wrongSha }]), /sha256 mismatch/);
        strict_1.default.ok(!(0, node_fs_1.existsSync)((0, node_path_1.join)(ctx.resourcesPath, "spa")));
    }
    finally {
        await ctx.cleanup();
    }
});
(0, node_test_1.default)("applyPayloads: applies multiple keys in order", async () => {
    const ctx = await makeContext();
    try {
        const stagingDir = (0, node_path_1.join)(ctx.userDataPath, "staged-update");
        await node_fs_1.promises.mkdir(stagingDir, { recursive: true });
        const entries = [];
        for (const key of ["spa", "content-packs"]) {
            const payload = (0, node_path_1.join)(stagingDir, `payload-${key}`);
            const { tarball, sha256 } = await makeFakeTarball(payload);
            const dest = (0, node_path_1.join)(stagingDir, `${key}.tar.gz`);
            await node_fs_1.promises.rename(tarball, dest);
            entries.push({ key, tarball: dest, sha256 });
        }
        const res = await (0, applier_1.applyPayloads)(ctx, entries);
        strict_1.default.deepEqual(res.applied.sort(), ["content-packs", "spa"]);
        strict_1.default.equal(await node_fs_1.promises.readFile((0, node_path_1.join)(ctx.resourcesPath, "spa", "index.html"), "utf8"), "<html>v2</html>");
        strict_1.default.equal(await node_fs_1.promises.readFile((0, node_path_1.join)(ctx.resourcesPath, "content-packs", "index.html"), "utf8"), "<html>v2</html>");
    }
    finally {
        await ctx.cleanup();
    }
});
(0, node_test_1.default)("rollback: restores most recent backup", async () => {
    const ctx = await makeContext();
    try {
        const live = (0, node_path_1.join)(ctx.resourcesPath, "spa");
        await node_fs_1.promises.mkdir(live, { recursive: true });
        await node_fs_1.promises.writeFile((0, node_path_1.join)(live, "index.html"), "<html>v1</html>");
        const stagingDir = (0, node_path_1.join)(ctx.userDataPath, "staged-update");
        await node_fs_1.promises.mkdir(stagingDir, { recursive: true });
        const payload = (0, node_path_1.join)(stagingDir, "v2");
        const { tarball, sha256 } = await makeFakeTarball(payload);
        const tarballDest = (0, node_path_1.join)(stagingDir, "spa.tar.gz");
        await node_fs_1.promises.rename(tarball, tarballDest);
        await (0, applier_1.applyPayloads)(ctx, [{ key: "spa", tarball: tarballDest, sha256 }]);
        strict_1.default.equal(await node_fs_1.promises.readFile((0, node_path_1.join)(ctx.resourcesPath, "spa", "index.html"), "utf8"), "<html>v2</html>");
        // Apply v3 (creates a second backup).
        const payload3 = (0, node_path_1.join)(stagingDir, "v3");
        await node_fs_1.promises.mkdir(payload3, { recursive: true });
        await node_fs_1.promises.writeFile((0, node_path_1.join)(payload3, "index.html"), "<html>v3</html>");
        const tarball3 = (0, node_path_1.join)(stagingDir, "v3.tar.gz");
        await (0, applier_1.createTarGz)(payload3, tarball3);
        const sha3 = await (0, applier_1.sha256OfFile)(tarball3);
        await (0, applier_1.applyPayloads)(ctx, [{ key: "spa", tarball: tarball3, sha256: sha3 }]);
        strict_1.default.equal(await node_fs_1.promises.readFile((0, node_path_1.join)(ctx.resourcesPath, "spa", "index.html"), "utf8"), "<html>v3</html>");
        const { rolled } = await (0, applier_1.rollback)(ctx, ["spa"]);
        strict_1.default.deepEqual(rolled, ["spa"]);
        strict_1.default.equal(await node_fs_1.promises.readFile((0, node_path_1.join)(ctx.resourcesPath, "spa", "index.html"), "utf8"), "<html>v2</html>");
    }
    finally {
        await ctx.cleanup();
    }
});
(0, node_test_1.default)("rollback: no-op when no backup exists", async () => {
    const ctx = await makeContext();
    try {
        const { rolled } = await (0, applier_1.rollback)(ctx, ["spa"]);
        strict_1.default.deepEqual(rolled, []);
    }
    finally {
        await ctx.cleanup();
    }
});
(0, node_test_1.default)("cleanStagedPayload removes the payload dir", async () => {
    const ctx = await makeContext();
    try {
        const pd = (0, node_path_1.join)(ctx.userDataPath, "staged-update", "payload");
        await node_fs_1.promises.mkdir(pd, { recursive: true });
        await node_fs_1.promises.writeFile((0, node_path_1.join)(pd, "x"), "x");
        await (0, applier_1.cleanStagedPayload)(ctx.userDataPath);
        strict_1.default.equal((0, node_fs_1.existsSync)(pd), false);
    }
    finally {
        await ctx.cleanup();
    }
});
(0, node_test_1.default)("listBackups enumerates by key", async () => {
    const ctx = await makeContext();
    try {
        // Two backups for spa, one for backend.
        for (const key of ["spa", "spa", "backend"]) {
            const live = (0, node_path_1.join)(ctx.resourcesPath, key);
            await node_fs_1.promises.mkdir(live, { recursive: true });
            await node_fs_1.promises.writeFile((0, node_path_1.join)(live, "x"), "x");
            const backup = `${live}.bak.${Date.now()}-${Math.random()}`;
            await node_fs_1.promises.rename(live, backup);
        }
        const bs = await (0, applier_1.listBackups)(ctx);
        strict_1.default.equal(bs.spa.length, 2);
        strict_1.default.equal(bs.backend.length, 1);
        strict_1.default.equal(bs["content-packs"].length, 0);
    }
    finally {
        await ctx.cleanup();
    }
});
//# sourceMappingURL=applier.test.js.map