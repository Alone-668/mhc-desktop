import test from "node:test"
import assert from "node:assert/strict"
import { createServer, Server } from "node:http"
import { createHash } from "node:crypto"
import { promises as fsp } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { AddressInfo } from "node:net"
import { downloadToFile, DownloadError } from "../downloader"

function startServer(handler: (req: any, res: any) => void): Promise<{ server: Server; url: string; close: () => Promise<void> }> {
  return new Promise((resolve) => {
    const server = createServer(handler)
    server.listen(0, "127.0.0.1", () => {
      const port = (server.address() as AddressInfo).port
      resolve({
        server,
        url: `http://127.0.0.1:${port}`,
        close: () => new Promise<void>((r) => server.close(() => r())),
      })
    })
  })
}

const PAYLOAD = Buffer.from("hello world".repeat(1024))
const PAYLOAD_SHA = createHash("sha256").update(PAYLOAD).digest("hex")

test("downloadToFile: writes file with correct sha256", async () => {
  const tmp = await fsp.mkdtemp(join(tmpdir(), "mhc-dl-"))
  try {
    const { url, close } = await startServer((_req, res) => {
      res.writeHead(200, { "content-length": String(PAYLOAD.length), "content-type": "application/octet-stream" })
      res.end(PAYLOAD)
    })
    const dest = join(tmp, "x.bin")
    const r = await downloadToFile(url + "/x.bin", dest, { expectedSha256: PAYLOAD_SHA })
    assert.equal(r.sha256, PAYLOAD_SHA)
    assert.equal(r.bytes, PAYLOAD.length)
    const data = await fsp.readFile(dest)
    assert.equal(data.length, PAYLOAD.length)
    await close()
  } finally {
    await fsp.rm(tmp, { recursive: true, force: true })
  }
})

test("downloadToFile: fails on HTTP 404", async () => {
  const tmp = await fsp.mkdtemp(join(tmpdir(), "mhc-dl-"))
  try {
    const { url, close } = await startServer((_req, res) => {
      res.writeHead(404)
      res.end()
    })
    await assert.rejects(
      downloadToFile(url + "/missing", join(tmp, "x.bin")),
      (err: unknown) => err instanceof DownloadError && /HTTP 404/.test((err as Error).message),
    )
    await close()
  } finally {
    await fsp.rm(tmp, { recursive: true, force: true })
  }
})

test("downloadToFile: fails on sha256 mismatch", async () => {
  const tmp = await fsp.mkdtemp(join(tmpdir(), "mhc-dl-"))
  try {
    const { url, close } = await startServer((_req, res) => {
      res.writeHead(200)
      res.end(PAYLOAD)
    })
    const wrong = "0".repeat(64)
    await assert.rejects(
      downloadToFile(url + "/x", join(tmp, "x.bin"), { expectedSha256: wrong }),
      (err: unknown) => err instanceof DownloadError && /sha256 mismatch/.test((err as Error).message),
    )
    // .part file should remain for diagnostics.
    assert.equal(await fsp.stat(join(tmp, "x.bin.part")).then(() => true).catch(() => false), true)
    await close()
  } finally {
    await fsp.rm(tmp, { recursive: true, force: true })
  }
})

test("downloadToFile: server abort mid-stream rejects", async () => {
  const tmp = await fsp.mkdtemp(join(tmpdir(), "mhc-dl-"))
  try {
    const { url, close } = await startServer((req, res) => {
      // Send partial, then hang up abruptly.
      res.writeHead(200)
      res.write(PAYLOAD.subarray(0, 100))
      setImmediate(() => {
        req.socket.destroy()
        res.end()
      })
    })
    await assert.rejects(
      downloadToFile(url + "/x", join(tmp, "x.bin")),
      DownloadError,
    )
    await close()
  } finally {
    await fsp.rm(tmp, { recursive: true, force: true })
  }
})

test("downloadToFile: cancel via AbortSignal", async () => {
  const tmp = await fsp.mkdtemp(join(tmpdir(), "mhc-dl-"))
  try {
    let pending: any = null
    const { url, close } = await startServer((req, res) => {
      pending = res
      res.writeHead(200)
      // Slow drip so we have time to abort.
      let i = 0
      const id = setInterval(() => {
        if (i++ > 100) {
          clearInterval(id)
          res.end()
          return
        }
        res.write(Buffer.alloc(1024, 0x61))
      }, 20)
      req.on("close", () => clearInterval(id))
    })
    const ctrl = new AbortController()
    setTimeout(() => ctrl.abort(), 100)
    await assert.rejects(
      downloadToFile(url + "/x", join(tmp, "x.bin"), { signal: ctrl.signal }),
      DownloadError,
    )
    if (pending) {
      try { pending.end() } catch { /* ignore */ }
    }
    await close()
  } finally {
    await fsp.rm(tmp, { recursive: true, force: true })
  }
})

test("downloadToFile: creates parent dirs", async () => {
  const tmp = await fsp.mkdtemp(join(tmpdir(), "mhc-dl-"))
  try {
    const { url, close } = await startServer((_req, res) => {
      res.writeHead(200)
      res.end(PAYLOAD)
    })
    const dest = join(tmp, "deeply", "nested", "x.bin")
    await downloadToFile(url + "/x", dest)
    assert.ok(await fsp.stat(dest))
    await close()
  } finally {
    await fsp.rm(tmp, { recursive: true, force: true })
  }
})

test("downloadToFile: reports progress bytes", async () => {
  const tmp = await fsp.mkdtemp(join(tmpdir(), "mhc-dl-"))
  try {
    const { url, close } = await startServer((_req, res) => {
      res.writeHead(200, { "content-length": String(PAYLOAD.length) })
      res.end(PAYLOAD)
    })
    const seen: number[] = []
    await downloadToFile(url + "/x", join(tmp, "x.bin"), {
      onProgress: (n) => seen.push(n),
      contentLength: PAYLOAD.length,
    })
    assert.ok(seen.length >= 1, "progress should fire at least once")
    assert.equal(seen[seen.length - 1], PAYLOAD.length, "final progress should be full size")
    await close()
  } finally {
    await fsp.rm(tmp, { recursive: true, force: true })
  }
})
