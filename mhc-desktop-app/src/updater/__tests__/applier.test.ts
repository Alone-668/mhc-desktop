import test from "node:test"
import assert from "node:assert/strict"
import { existsSync, promises as fsp } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import {
  applyPayloads,
  atomicReplace,
  cleanStagedPayload,
  createTarGz,
  extractTarGz,
  listBackups,
  rollback,
  sha256OfFile,
  type ApplyContext,
  type ApplyKey,
} from "../applier"

/** Build a small fake payload: a directory with 3 files, tar+gzip it
 *  via the system tar (using createTarGz so tests avoid the raw-spawn
 *  argv quirks). Returns the path to the tarball + SHA. */
async function makeFakeTarball(payloadDir: string): Promise<{ tarball: string; sha256: string }> {
  await fsp.mkdir(payloadDir, { recursive: true })
  await fsp.writeFile(join(payloadDir, "index.html"), "<html>v2</html>")
  await fsp.mkdir(join(payloadDir, "assets"), { recursive: true })
  await fsp.writeFile(join(payloadDir, "assets", "main.js"), "console.log('v2')")
  await fsp.writeFile(join(payloadDir, "brand.svg"), "<svg/>")
  const tarball = payloadDir + ".tar.gz"
  await createTarGz(payloadDir, tarball)
  const sha256 = await sha256OfFile(tarball)
  return { tarball, sha256 }
}

async function makeContext(): Promise<ApplyContext & { cleanup: () => Promise<void> }> {
  const root = await fsp.mkdtemp(join(tmpdir(), "mhc-upd-"))
  const resourcesPath = join(root, "resources")
  const userDataPath = join(root, "userData")
  await fsp.mkdir(resourcesPath, { recursive: true })
  await fsp.mkdir(userDataPath, { recursive: true })
  return {
    resourcesPath,
    userDataPath,
    cleanup: async () => fsp.rm(root, { recursive: true, force: true }),
  }
}

test("sha256OfFile computes the correct hash", async () => {
  const tmp = await fsp.mkdtemp(join(tmpdir(), "mhc-sha-"))
  try {
    const p = join(tmp, "f.bin")
    await fsp.writeFile(p, "hello")
    const expected = (await import("node:crypto")).createHash("sha256").update("hello").digest("hex")
    assert.equal(await sha256OfFile(p), expected)
  } finally {
    await fsp.rm(tmp, { recursive: true, force: true })
  }
})

test("atomicReplace: rename within same volume", async () => {
  const tmp = await fsp.mkdtemp(join(tmpdir(), "mhc-atr-"))
  try {
    const src = join(tmp, "src")
    const dst = join(tmp, "dst")
    await fsp.mkdir(src)
    await fsp.writeFile(join(src, "x"), "x")
    await atomicReplace(src, dst)
    assert.equal(await fsp.readFile(join(dst, "x"), "utf8"), "x")
  } finally {
    await fsp.rm(tmp, { recursive: true, force: true })
  }
})

test("extractTarGz round-trip", async () => {
  const tmp = await fsp.mkdtemp(join(tmpdir(), "mhc-tar-"))
  try {
    const src = join(tmp, "src")
    const { tarball } = await makeFakeTarball(src)
    const dest = join(tmp, "out")
    await extractTarGz(tarball, dest)
    assert.equal(await fsp.readFile(join(dest, "index.html"), "utf8"), "<html>v2</html>")
    assert.equal(await fsp.readFile(join(dest, "assets", "main.js"), "utf8"), "console.log('v2')")
  } finally {
    await fsp.rm(tmp, { recursive: true, force: true })
  }
})

test("applyPayloads: extracts, swaps live aside, installs payload", async () => {
  const ctx = await makeContext()
  try {
    const live = join(ctx.resourcesPath, "spa")
    await fsp.mkdir(live, { recursive: true })
    await fsp.writeFile(join(live, "index.html"), "<html>v1</html>")

    const stagingDir = join(ctx.userDataPath, "staged-update")
    await fsp.mkdir(stagingDir, { recursive: true })
    const payload = join(stagingDir, "v2-spa")
    const { tarball, sha256 } = await makeFakeTarball(payload)
    const tarballDest = join(stagingDir, "spa.tar.gz")
    await fsp.rename(tarball, tarballDest)

    const res = await applyPayloads(ctx, [{ key: "spa", tarball: tarballDest, sha256 }])
    assert.deepEqual(res.applied, ["spa"])
    assert.equal(await fsp.readFile(join(ctx.resourcesPath, "spa", "index.html"), "utf8"), "<html>v2</html>")

    assert.ok(res.backups.spa)
    const backup = res.backups.spa!
    assert.ok(backup.includes(".bak."))
    assert.equal(await fsp.readFile(join(backup, "index.html"), "utf8"), "<html>v1</html>")
  } finally {
    await ctx.cleanup()
  }
})

test("applyPayloads: rejects when tarball sha mismatches manifest", async () => {
  const ctx = await makeContext()
  try {
    const stagingDir = join(ctx.userDataPath, "staged-update")
    await fsp.mkdir(stagingDir, { recursive: true })
    const payload = join(stagingDir, "v2-spa")
    const { tarball } = await makeFakeTarball(payload)
    const tarballDest = join(stagingDir, "spa.tar.gz")
    await fsp.rename(tarball, tarballDest)
    const wrongSha = "0".repeat(64)
    await assert.rejects(
      applyPayloads(ctx, [{ key: "spa", tarball: tarballDest, sha256: wrongSha }]),
      /sha256 mismatch/,
    )
    assert.ok(!existsSync(join(ctx.resourcesPath, "spa")))
  } finally {
    await ctx.cleanup()
  }
})

test("applyPayloads: applies multiple keys in order", async () => {
  const ctx = await makeContext()
  try {
    const stagingDir = join(ctx.userDataPath, "staged-update")
    await fsp.mkdir(stagingDir, { recursive: true })
    const entries = []
    for (const key of ["spa", "content-packs"] as ApplyKey[]) {
      const payload = join(stagingDir, `payload-${key}`)
      const { tarball, sha256 } = await makeFakeTarball(payload)
      const dest = join(stagingDir, `${key}.tar.gz`)
      await fsp.rename(tarball, dest)
      entries.push({ key, tarball: dest, sha256 })
    }
    const res = await applyPayloads(ctx, entries)
    assert.deepEqual(res.applied.sort(), ["content-packs", "spa"])
    assert.equal(await fsp.readFile(join(ctx.resourcesPath, "spa", "index.html"), "utf8"), "<html>v2</html>")
    assert.equal(await fsp.readFile(join(ctx.resourcesPath, "content-packs", "index.html"), "utf8"), "<html>v2</html>")
  } finally {
    await ctx.cleanup()
  }
})

test("rollback: restores most recent backup", async () => {
  const ctx = await makeContext()
  try {
    const live = join(ctx.resourcesPath, "spa")
    await fsp.mkdir(live, { recursive: true })
    await fsp.writeFile(join(live, "index.html"), "<html>v1</html>")

    const stagingDir = join(ctx.userDataPath, "staged-update")
    await fsp.mkdir(stagingDir, { recursive: true })
    const payload = join(stagingDir, "v2")
    const { tarball, sha256 } = await makeFakeTarball(payload)
    const tarballDest = join(stagingDir, "spa.tar.gz")
    await fsp.rename(tarball, tarballDest)
    await applyPayloads(ctx, [{ key: "spa", tarball: tarballDest, sha256 }])
    assert.equal(await fsp.readFile(join(ctx.resourcesPath, "spa", "index.html"), "utf8"), "<html>v2</html>")

    // Apply v3 (creates a second backup).
    const payload3 = join(stagingDir, "v3")
    await fsp.mkdir(payload3, { recursive: true })
    await fsp.writeFile(join(payload3, "index.html"), "<html>v3</html>")
    const tarball3 = join(stagingDir, "v3.tar.gz")
    await createTarGz(payload3, tarball3)
    const sha3 = await sha256OfFile(tarball3)
    await applyPayloads(ctx, [{ key: "spa", tarball: tarball3, sha256: sha3 }])
    assert.equal(await fsp.readFile(join(ctx.resourcesPath, "spa", "index.html"), "utf8"), "<html>v3</html>")

    const { rolled } = await rollback(ctx, ["spa"])
    assert.deepEqual(rolled, ["spa"])
    assert.equal(await fsp.readFile(join(ctx.resourcesPath, "spa", "index.html"), "utf8"), "<html>v2</html>")
  } finally {
    await ctx.cleanup()
  }
})

test("rollback: no-op when no backup exists", async () => {
  const ctx = await makeContext()
  try {
    const { rolled } = await rollback(ctx, ["spa"])
    assert.deepEqual(rolled, [])
  } finally {
    await ctx.cleanup()
  }
})

test("cleanStagedPayload removes the payload dir", async () => {
  const ctx = await makeContext()
  try {
    const pd = join(ctx.userDataPath, "staged-update", "payload")
    await fsp.mkdir(pd, { recursive: true })
    await fsp.writeFile(join(pd, "x"), "x")
    await cleanStagedPayload(ctx.userDataPath)
    assert.equal(existsSync(pd), false)
  } finally {
    await ctx.cleanup()
  }
})

test("listBackups enumerates by key", async () => {
  const ctx = await makeContext()
  try {
    // Two backups for spa, one for backend.
    for (const key of ["spa", "spa", "backend"] as ApplyKey[]) {
      const live = join(ctx.resourcesPath, key)
      await fsp.mkdir(live, { recursive: true })
      await fsp.writeFile(join(live, "x"), "x")
      const backup = `${live}.bak.${Date.now()}-${Math.random()}`
      await fsp.rename(live, backup)
    }
    const bs = await listBackups(ctx)
    assert.equal(bs.spa.length, 2)
    assert.equal(bs.backend.length, 1)
    assert.equal(bs["content-packs"].length, 0)
  } finally {
    await ctx.cleanup()
  }
})
