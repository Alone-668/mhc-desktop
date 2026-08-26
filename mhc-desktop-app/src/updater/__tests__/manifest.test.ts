import test from "node:test"
import assert from "node:assert/strict"
import {
  parseManifest,
  compareVersions,
  diffManifest,
  fetchManifestWithMirrors,
  ManifestError,
  type Manifest,
} from "../manifest"

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
    backend: { version: "0.2.1", url: "https://cdn/be.tgz", sha256: "c".repeat(64), size: 300, python_tag: "20250814-x86_64-pc-windows-msvc-shared-install_only" },
  },
  release_notes: "hello",
}

test("parseManifest: accepts a complete manifest", () => {
  const m = parseManifest(VALID)
  assert.equal(m.manifest_version, 1)
  assert.equal(m.tier2?.spa?.version, "0.2.1")
})

test("parseManifest: rejects non-objects", () => {
  assert.throws(() => parseManifest("nope"), ManifestError)
  assert.throws(() => parseManifest(null), ManifestError)
})

test("parseManifest: rejects unknown manifest_version", () => {
  assert.throws(() => parseManifest({ ...VALID, manifest_version: 99 }), /unsupported manifest_version=99/)
})

test("parseManifest: rejects invalid channel", () => {
  assert.throws(() => parseManifest({ ...VALID, channel: "rc" }), /invalid channel=rc/)
})

test("parseManifest: rejects tier entries missing fields", () => {
  assert.throws(
    () => parseManifest({ ...VALID, tier2: { spa: { version: "x", url: "u" } } }),
    /tier2.spa.sha256 missing/,
  )
})

test("parseManifest: tier2/tier3 fully optional", () => {
  const minimal = {
    manifest_version: 1,
    channel: "stable" as const,
    released_at: "2026-01-01T00:00:00Z",
    min_app_version: "0.0.1",
  }
  const m = parseManifest(minimal)
  assert.equal(m.tier2, undefined)
  assert.equal(m.tier3, undefined)
})

test("compareVersions: numeric semver", () => {
  assert.equal(compareVersions("0.1.0", "0.2.0") < 0, true)
  assert.equal(compareVersions("0.2.0", "0.2.0"), 0)
  assert.equal(compareVersions("1.0.0", "0.99.99") > 0, true)
})

test("compareVersions: date-shaped versions", () => {
  assert.equal(compareVersions("2026-09-01", "2026-09-15") < 0, true)
  assert.equal(compareVersions("2026-09-15", "2026-09-15"), 0)
})

test("compareVersions: trailing zero segments are equal", () => {
  // Semver treats "0.1" and "0.1.0" as equivalent; neither is "longer wins".
  assert.equal(compareVersions("0.1", "0.1.0"), 0)
  assert.equal(compareVersions("0.1.0", "0.1"), 0)
  assert.equal(compareVersions("0.2.1", "0.2.1.1") < 0, true)
  assert.equal(compareVersions("0.2.1.1", "0.2.1") > 0, true)
})

test("diffManifest: app below min_app_version triggers forceTier1", () => {
  const out = diffManifest(VALID, { app: "0.0.5" })
  assert.equal(out.forceTier1, true)
})

test("diffManifest: app at min_app_version does not force Tier 1", () => {
  const out = diffManifest(VALID, { app: "0.1.0" })
  assert.equal(out.forceTier1, false)
})

test("diffManifest: marks newer components as available", () => {
  // current spa 0.2.0 < manifest spa 0.2.1 -> available
  // current backend 0.2.1 == manifest backend 0.2.1 -> not available
  // current content_packs undefined < 2026-09-15 -> available
  const out = diffManifest(VALID, { app: "0.1.0", spa: "0.2.0", backend: "0.2.1" })
  assert.ok(out.spa)
  assert.equal(out.spa?.version, "0.2.1")
  assert.equal(out.backend, undefined)
  assert.ok(out.content_packs)
})

test("diffManifest: returns everything when current is empty", () => {
  const out = diffManifest(VALID, { app: "0.1.0" })
  assert.ok(out.spa)
  assert.ok(out.content_packs)
  assert.ok(out.backend)
})

test("fetchManifestWithMirrors: returns first successful source", async () => {
  const origFetch = globalThis.fetch
  globalThis.fetch = (async (url: any) => {
    if (String(url).includes("primary")) {
      return { ok: true, status: 200, text: async () => JSON.stringify(VALID) } as any
    }
    return { ok: false, status: 503, text: async () => "" } as any
  }) as any
  try {
    const { manifest, source } = await fetchManifestWithMirrors(
      "https://primary.example.com/update.json",
      ["https://mirror-a.example.com", "https://mirror-b.example.com"],
    )
    assert.equal(manifest.tier2?.spa?.version, "0.2.1")
    assert.equal(source, "https://primary.example.com/update.json")
  } finally {
    globalThis.fetch = origFetch
  }
})

test("fetchManifestWithMirrors: falls back to first mirror when primary fails", async () => {
  const calls: string[] = []
  const origFetch = globalThis.fetch
  globalThis.fetch = (async (url: any) => {
    calls.push(String(url))
    if (String(url).includes("primary")) {
      return { ok: false, status: 404, text: async () => "" } as any
    }
    if (String(url).includes("mirror-a")) {
      return { ok: false, status: 500, text: async () => "" } as any
    }
    return { ok: true, status: 200, text: async () => JSON.stringify(VALID) } as any
  }) as any
  try {
    const { manifest, source } = await fetchManifestWithMirrors(
      "https://primary.example.com/update.json",
      ["https://mirror-a.example.com", "https://mirror-b.example.com"],
    )
    assert.equal(manifest.min_app_version, "0.1.0")
    assert.ok(source.includes("mirror-b"))
    assert.equal(calls.length, 3)
  } finally {
    globalThis.fetch = origFetch
  }
})

test("fetchManifestWithMirrors: throws when all fail", async () => {
  const origFetch = globalThis.fetch
  globalThis.fetch = (async () => ({ ok: false, status: 500, text: async () => "" })) as any
  try {
    await assert.rejects(
      fetchManifestWithMirrors("https://primary.example.com/update.json", []),
      /all manifest sources failed/,
    )
  } finally {
    globalThis.fetch = origFetch
  }
})
