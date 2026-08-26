import test from "node:test"
import assert from "node:assert/strict"
import { promises as fsp } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { EventEmitter } from "node:events"
import { createHash } from "node:crypto"
import { spawn } from "node:child_process"
import {
  createRollout,
  type RolloutContext,
  type RolloutHandle,
} from "../rollout"
import { createTarGz } from "../applier"
import type { Manifest } from "../manifest"
import type { UpdaterPrefs } from "../prefs"
import { memoryLogger } from "../log"

const VALID: Manifest = {
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
}

const FAKE_PREF: UpdaterPrefs = {
  manifestUrl: "https://primary.example.com/update.json",
  channel: "stable",
  autoUpdate: true,
  checkIntervalMs: 60_000,
}

async function makeCtx(overrides: Partial<RolloutContext> = {}): Promise<RolloutContext & { cleanup: () => Promise<void> }> {
  const root = await fsp.mkdtemp(join(tmpdir(), "mhc-rollout-"))
  const resourcesPath = join(root, "resources")
  const userDataPath = join(root, "userData")
  await fsp.mkdir(resourcesPath, { recursive: true })
  await fsp.mkdir(userDataPath, { recursive: true })
  // Each ctx gets its own prefs copy so a test that mutates
  // ``ctx.prefs.autoUpdate = false`` doesn't leak into the next test.
  const prefs = { ...FAKE_PREF }
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
    cleanup: async () => fsp.rm(root, { recursive: true, force: true }),
  }
}

/** Build a fake manifest fetcher that returns the given manifest on
 *  the first call. */
function fakeManifestFetcher(manifest: Manifest | null, err?: Error) {
  return async (url: string) => {
    if (err) throw err
    return {
      ok: true,
      status: 200,
      text: async () => JSON.stringify(manifest),
      arrayBuffer: async () => new ArrayBuffer(0),
    }
  }
}

async function makeTarball(outFile: string, content: { [k: string]: string }): Promise<string> {
  const stage = outFile + ".stage"
  await fsp.mkdir(stage, { recursive: true })
  for (const [name, body] of Object.entries(content)) {
    await fsp.writeFile(join(stage, name), body)
  }
  await createTarGz(stage, outFile)
  await fsp.rm(stage, { recursive: true, force: true })
  return createHash("sha256").update(await fsp.readFile(outFile)).digest("hex")
}

// ----- tests -----

test("rollout: checkNow transitions idle -> checking -> update_available when updates exist", async () => {
  const ctx = await makeCtx()
  const origFetch = globalThis.fetch
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  globalThis.fetch = (async (url: any) => {
    if (String(url).includes("update.json")) {
      return {
        ok: true,
        status: 200,
        text: async () => JSON.stringify(VALID),
        arrayBuffer: async () => new ArrayBuffer(0),
        headers: new Map(),
      } as any
    }
    return origFetch(url)
  }) as any
  try {
    const log = memoryLogger()
    const states: string[] = []
    const handle = createRollout(ctx, {
      logger: log,
      onState: (i) => states.push(i.state),
    })
    const r = await handle.checkNow()
    assert.equal(r.state, "update_available")
    assert.ok(r.available?.spa)
    assert.ok(r.available?.content_packs)
    assert.ok(r.available?.backend)
    assert.ok(states.includes("checking"))
    assert.ok(states.includes("update_available"))
  } finally {
    globalThis.fetch = origFetch
    await ctx.cleanup()
  }
})

test("rollout: checkNow transitions to download_failed when manifest unreachable", async () => {
  const ctx = await makeCtx()
  const origFetch = globalThis.fetch
  globalThis.fetch = (async () => ({ ok: false, status: 500, text: async () => "", arrayBuffer: async () => new ArrayBuffer(0), headers: new Map() })) as any
  try {
    const handle = createRollout(ctx, { logger: memoryLogger() })
    const r = await handle.checkNow()
    assert.equal(r.state, "download_failed")
    assert.ok(r.error)
  } finally {
    globalThis.fetch = origFetch
    await ctx.cleanup()
  }
})

test("rollout: checkNow returns idle when nothing newer", async () => {
  const ctx = await makeCtx({
    current: {
      app: "0.1.0",
      spa: "0.2.1",
      content_packs: "2026-09-15",
      backend: "0.2.1",
    },
  })
  const origFetch = globalThis.fetch
  globalThis.fetch = (async () => ({ ok: true, status: 200, text: async () => JSON.stringify(VALID), arrayBuffer: async () => new ArrayBuffer(0), headers: new Map() })) as any
  try {
    const handle = createRollout(ctx, { logger: memoryLogger() })
    const r = await handle.checkNow()
    assert.equal(r.state, "idle")
    assert.equal(r.available, undefined)
  } finally {
    globalThis.fetch = origFetch
    await ctx.cleanup()
  }
})

test("rollout: forceTier1 when app below min_app_version", async () => {
  const ctx = await makeCtx({ appVersion: "0.0.9", current: { app: "0.0.9" } })
  const origFetch = globalThis.fetch
  globalThis.fetch = (async () => ({ ok: true, status: 200, text: async () => JSON.stringify(VALID), arrayBuffer: async () => new ArrayBuffer(0), headers: new Map() })) as any
  try {
    const handle = createRollout(ctx, { logger: memoryLogger() })
    const r = await handle.checkNow()
    assert.equal(r.state, "update_available")
    assert.equal(r.forceTier1, true)
  } finally {
    globalThis.fetch = origFetch
    await ctx.cleanup()
  }
})

test("rollout: respects autoUpdate=false", async () => {
  const ctx = await makeCtx()
  ctx.prefs.autoUpdate = false
  try {
    const handle = createRollout(ctx, { logger: memoryLogger() })
    const r = await handle.checkNow()
    assert.equal(r.state, "idle")
  } finally {
    await ctx.cleanup()
  }
})

test("rollout: installAvailable downloads via stubbed fetch", async () => {
  const ctx = await makeCtx()
  // Pre-make a tarball on disk.
  const stagedDir = join(ctx.userDataPath, "staged-update")
  await fsp.mkdir(stagedDir, { recursive: true })
  const tarPath = join(stagedDir, "spa.tar.gz.src")
  const tarSha = await makeTarball(tarPath, { "index.html": "<html>v2</html>" })
  const tarBytes = await fsp.readFile(tarPath)
  // Manifest with the URL pointing at a path we'll intercept in
  // fetch. The url host doesn't matter; the fetcher just needs to
  // match by suffix.
  const m: Manifest = {
    ...VALID,
    tier2: {
      spa: { version: "99.0.0", url: "http://stubhost/spa.tar.gz", sha256: tarSha, size: tarBytes.length },
    },
    tier3: undefined,
  }
  const origFetch = globalThis.fetch
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  globalThis.fetch = (async (url: any) => {
    const s = String(url)
    if (s.endsWith("update.json")) {
      return { ok: true, status: 200, text: async () => JSON.stringify(m), arrayBuffer: async () => new ArrayBuffer(0), headers: new Map([["content-length", "100"]]) } as any
    }
    if (s.endsWith("spa.tar.gz")) {
      return {
        ok: true,
        status: 200,
        body: new ReadableStream({
          start(c) { c.enqueue(new Uint8Array(tarBytes)); c.close() },
        }),
        headers: new Map([["content-length", String(tarBytes.length)]]),
      } as any
    }
    return { ok: false, status: 404, text: async () => "", arrayBuffer: async () => new ArrayBuffer(0), headers: new Map() } as any
  }) as any
  try {
    const log = memoryLogger()
    const handle = createRollout(ctx, { logger: log })
    await handle.checkNow()
    const r = await handle.installAvailable()
    assert.equal(r.state, "staged")
    // Staged manifest + tarball present
    const stagedManifest = JSON.parse(await fsp.readFile(join(stagedDir, "manifest.json"), "utf8"))
    assert.equal(stagedManifest.tier2.spa.version, "99.0.0")
    assert.ok(await fsp.stat(join(stagedDir, "spa.tar.gz")))
  } finally {
    globalThis.fetch = origFetch
    await ctx.cleanup()
  }
})

test("rollout: installAvailable fails download when sha mismatches", async () => {
  const ctx = await makeCtx()
  const stagedDir = join(ctx.userDataPath, "staged-update")
  await fsp.mkdir(stagedDir, { recursive: true })
  const tarPath = join(stagedDir, "spa.tar.gz.src")
  const tarSha = await makeTarball(tarPath, { "index.html": "<html>v2</html>" })
  const tarBytes = await fsp.readFile(tarPath)
  const wrongSha = "0".repeat(64)
  const m: Manifest = {
    ...VALID,
    tier2: { spa: { version: "99.0.0", url: "http://stubhost/spa.tar.gz", sha256: wrongSha, size: tarBytes.length } },
    tier3: undefined,
  }
  const origFetch = globalThis.fetch
  globalThis.fetch = (async (url: any) => {
    const s = String(url)
    if (s.endsWith("update.json")) return { ok: true, status: 200, text: async () => JSON.stringify(m), arrayBuffer: async () => new ArrayBuffer(0), headers: new Map() } as any
    if (s.endsWith("spa.tar.gz")) {
      return { ok: true, status: 200, body: new ReadableStream({ start(c) { c.enqueue(new Uint8Array(tarBytes)); c.close() } }), headers: new Map([["content-length", String(tarBytes.length)]]) } as any
    }
    return { ok: false, status: 404, text: async () => "", arrayBuffer: async () => new ArrayBuffer(0), headers: new Map() } as any
  }) as any
  try {
    const handle = createRollout(ctx, { logger: memoryLogger() })
    await handle.checkNow()
    await assert.rejects(handle.installAvailable(), /sha256 mismatch/)
  } finally {
    globalThis.fetch = origFetch
    await ctx.cleanup()
  }
})

test("rollout: applyPending swaps live with staged and writes last-good on commit", async () => {
  const ctx = await makeCtx()
  // Pre-populate live spa with v1.
  const live = join(ctx.resourcesPath, "spa")
  await fsp.mkdir(live, { recursive: true })
  await fsp.writeFile(join(live, "index.html"), "<html>v1</html>")
  // Stage a v2 tarball.
  const stagedDir = join(ctx.userDataPath, "staged-update")
  await fsp.mkdir(stagedDir, { recursive: true })
  const tarPath = join(stagedDir, "spa.tar.gz")
  const sha = await makeTarball(tarPath, { "index.html": "<html>v2</html>" })
  // Write a staged manifest so applyPending finds something.
  const m: Manifest = {
    ...VALID,
    tier2: { spa: { version: "0.2.1", url: "http://stubhost/spa.tar.gz", sha256: sha, size: 9999 } },
    tier3: undefined,
  }
  await fsp.writeFile(join(stagedDir, "manifest.json"), JSON.stringify(m))
  const handle = createRollout(ctx, { logger: memoryLogger() })
  const r = await handle.applyPending()
  assert.deepEqual(r.applied, ["spa"])
  assert.equal(await fsp.readFile(join(ctx.resourcesPath, "spa", "index.html"), "utf8"), "<html>v2</html>")
  // State should be committed; last-good.json written only after
  // commitIfHealthy is called by main.ts.
  assert.equal(handle.getInfo().state, "committed")
  await handle.commitIfHealthy({ versions: { spa: "0.2.1" } })
  const lg = JSON.parse(await fsp.readFile(join(ctx.userDataPath, "last-good.json"), "utf8"))
  assert.equal(lg.spa, "0.2.1")
  assert.equal(lg.app, "0.1.0")
  await ctx.cleanup()
})

test("rollout: rollbackNow restores from backup", async () => {
  const ctx = await makeCtx()
  const live = join(ctx.resourcesPath, "spa")
  await fsp.mkdir(live, { recursive: true })
  await fsp.writeFile(join(live, "index.html"), "<html>v1</html>")
  const stagedDir = join(ctx.userDataPath, "staged-update")
  await fsp.mkdir(stagedDir, { recursive: true })
  const tarPath = join(stagedDir, "spa.tar.gz")
  const sha = await makeTarball(tarPath, { "index.html": "<html>v2</html>" })
  const m: Manifest = {
    ...VALID,
    tier2: { spa: { version: "0.2.1", url: "http://stubhost/spa.tar.gz", sha256: sha, size: 9999 } },
    tier3: undefined,
  }
  await fsp.writeFile(join(stagedDir, "manifest.json"), JSON.stringify(m))
  const handle = createRollout(ctx, { logger: memoryLogger() })
  await handle.applyPending()
  assert.equal(await fsp.readFile(join(ctx.resourcesPath, "spa", "index.html"), "utf8"), "<html>v2</html>")
  const r = await handle.rollbackNow()
  assert.deepEqual(r.rolled, ["spa"])
  assert.equal(await fsp.readFile(join(ctx.resourcesPath, "spa", "index.html"), "utf8"), "<html>v1</html>")
  await ctx.cleanup()
})

test("rollout: onStateChange emits transitions", async () => {
  const ctx = await makeCtx()
  const handle = createRollout(ctx, { logger: memoryLogger() })
  const emitter = new EventEmitter()
  const seen: string[] = []
  const off = handle.onStateChange((i) => {
    seen.push(i.state)
    emitter.emit("got", i)
  })
  // Manually transition to test emitter.
  // checkNow will move idle -> checking -> update_available
  const origFetch = globalThis.fetch
  globalThis.fetch = (async () => ({ ok: true, status: 200, text: async () => JSON.stringify(VALID), arrayBuffer: async () => new ArrayBuffer(0), headers: new Map() })) as any
  try {
    await handle.checkNow()
    assert.ok(seen.includes("checking"))
    assert.ok(seen.includes("update_available"))
  } finally {
    globalThis.fetch = origFetch
    off()
    await ctx.cleanup()
  }
})
