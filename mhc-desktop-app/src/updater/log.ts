/**
 * Tiny append-only log writer for updater events. Distinct from
 * main.ts's ``appendLog`` because:
 *
 *   - updater-specific lifecycle events are easier to grep for
 *   - tests don't need to mock console.log — they get a log array
 *
 * Writes ``update.log`` under ``userData``. Rotates when > 1 MB.
 */

import { promises as fsp } from "node:fs"
import { join } from "node:path"

const MAX_BYTES = 1024 * 1024

export interface UpdaterLogger {
  info(msg: string): void
  warn(msg: string): void
  error(msg: string): void
  flush(): Promise<void>
}

export function createUpdaterLogger(userDataPath: string): UpdaterLogger {
  const file = join(userDataPath, "update.log")
  const write = (line: string) => {
    const stamped = `[${shanghaiTs()}] ${line}\n`
    fsp.stat(file).then((s) => {
      if (s.size > MAX_BYTES) fsp.rename(file, file + ".1").catch(() => undefined)
    }).catch(() => undefined)
    return fsp.appendFile(file, stamped, "utf8").catch(() => undefined)
  }
  return {
    info: (m) => void write(`[info] ${m}`),
    warn: (m) => void write(`[warn] ${m}`),
    error: (m) => void write(`[error] ${m}`),
    flush: async () => undefined,
  }
}

/** In-memory logger for tests. Mutate ``lines`` to assert on history. */
export function memoryLogger(): UpdaterLogger & { lines: string[] } {
  const lines: string[] = []
  const push = (level: string, m: string) => lines.push(`[${level}] ${m}`)
  return {
    lines,
    info: (m) => push("info", m),
    warn: (m) => push("warn", m),
    error: (m) => push("error", m),
    flush: async () => undefined,
  }
}

function shanghaiTs(): string {
  return new Date(Date.now() + 8 * 3600 * 1000).toISOString().replace("Z", "+08:00")
}
