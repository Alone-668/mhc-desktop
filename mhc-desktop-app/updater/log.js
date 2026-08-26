"use strict";
/**
 * Tiny append-only log writer for updater events. Distinct from
 * main.ts's ``appendLog`` because:
 *
 *   - updater-specific lifecycle events are easier to grep for
 *   - tests don't need to mock console.log — they get a log array
 *
 * Writes ``update.log`` under ``userData``. Rotates when > 1 MB.
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.createUpdaterLogger = createUpdaterLogger;
exports.memoryLogger = memoryLogger;
const node_fs_1 = require("node:fs");
const node_path_1 = require("node:path");
const MAX_BYTES = 1024 * 1024;
function createUpdaterLogger(userDataPath) {
    const file = (0, node_path_1.join)(userDataPath, "update.log");
    const write = (line) => {
        const stamped = `[${shanghaiTs()}] ${line}\n`;
        node_fs_1.promises.stat(file).then((s) => {
            if (s.size > MAX_BYTES)
                node_fs_1.promises.rename(file, file + ".1").catch(() => undefined);
        }).catch(() => undefined);
        return node_fs_1.promises.appendFile(file, stamped, "utf8").catch(() => undefined);
    };
    return {
        info: (m) => void write(`[info] ${m}`),
        warn: (m) => void write(`[warn] ${m}`),
        error: (m) => void write(`[error] ${m}`),
        flush: async () => undefined,
    };
}
/** In-memory logger for tests. Mutate ``lines`` to assert on history. */
function memoryLogger() {
    const lines = [];
    const push = (level, m) => lines.push(`[${level}] ${m}`);
    return {
        lines,
        info: (m) => push("info", m),
        warn: (m) => push("warn", m),
        error: (m) => push("error", m),
        flush: async () => undefined,
    };
}
function shanghaiTs() {
    return new Date(Date.now() + 8 * 3600 * 1000).toISOString().replace("Z", "+08:00");
}
//# sourceMappingURL=log.js.map