"use strict";
/**
 * State machine for the update lifecycle. Pure data — no I/O. The
 * orchestrator (rollout.ts) handles transitions; UI / IPC code
 * subscribes to the event emitter for visualization.
 *
 * See ``docs/UPDATE-MECHANISM.md`` §4 for the canonical diagram.
 */
Object.defineProperty(exports, "__esModule", { value: true });
exports.StateTransitionError = exports.INITIAL_INFO = void 0;
exports.canTransition = canTransition;
exports.assertTransition = assertTransition;
exports.INITIAL_INFO = { state: "idle" };
/** Allowed transitions. Any transition not listed here throws at
 *  runtime — guards against the orchestrator stepping on itself
 *  during async races. */
const ALLOWED = {
    idle: ["checking"],
    checking: ["update_available", "idle", "download_failed"],
    update_available: ["downloading", "idle"],
    downloading: ["staged", "download_failed", "idle"],
    download_failed: ["checking", "idle"],
    staged: ["applying", "idle"],
    applying: ["committed", "rolled_back"],
    committed: ["idle"],
    rolled_back: ["idle", "checking"],
};
function canTransition(from, to) {
    return ALLOWED[from].includes(to);
}
class StateTransitionError extends Error {
    constructor(from, to) {
        super(`illegal transition ${from} -> ${to}`);
        this.name = "StateTransitionError";
    }
}
exports.StateTransitionError = StateTransitionError;
function assertTransition(from, to) {
    if (!canTransition(from, to))
        throw new StateTransitionError(from, to);
}
//# sourceMappingURL=state.js.map