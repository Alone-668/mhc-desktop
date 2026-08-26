"use strict";
/**
 * Tiny append-only log writer for updater events. Distinct from
 * main.ts's ``appendLog`` because:
 *
 *   - updater-specific lifecycle events are easier to grep for
 *   - we don't want every tray menu click to spam the main log
 *   - tests don't need to mock console.log — they get a log array
 *
 * Writes ``update.log`` under ``userData``. Rotates when > 1 MB.
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.createUpdaterLogger = createUpdaterLogger;
exports.createMemoryLogger = createMemoryLogger;
const node_fs_1 = require("node:fs");
const node_path_1 = require("node:path");
const MAX_BYTES = 1024 * 1024;
function createUpdaterLogger(userDataPath) {
    const file = (0, node_path_1.join)(userDataPath, "update.log");
    async function write(line) {
        const stamped = `[${shanghaiTs()}] ${line}\n`;
        try {
            try {
                const stat = await node_fs_1.promises.stat(file);
                if (stat.size > MAX_BYTES) {
                    await node_fs_1.promises.rename(file, file + ".1");
                }
            }
            catch {
                /* first write */
            }
            await node_fs_1.promises.appendFile(file, stamped, "utf8");
        }
        catch {
            /* userData not writable — best effort */
        }
    }
    return {
        info: (m) => void write(`[info] ${m}`),
        warn: (m) => void write(`[warn] ${m}`),
        error: (m) => void write(`[error] ${m}`),
        flush: async () => undefined,
    };
}
/** Memory-only logger for tests. */
function createMemoryLogger() {
    const lines = [];
    const stamp = (level, m) => lines.push(`[${level}] ${m}`);
    return {
        lines,
        info: (m) => stamp("info", m),
        warn: (m) => stamp("warn", m),
        error: (m) => stamp("error", m),
        flush: async () => undefined,
    };
}
function shanghaiTs() {
    return new Date(Date.now() + 8 * 3600 * 1000).toISOString().replace("Z", "+08:00");
}
//# sourceMappingURL=log.js.map