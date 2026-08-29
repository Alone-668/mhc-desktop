"""Per-session stream registry.

Each running chat call registers a cancel token keyed by session_id so:

* the SSE handler can yield a `cancelled` event then tear down when the
  client disconnects or asks the session to stop, without crashing the
  surrounding StreamingResponse;
* the lifespan / SIGTERM handler can sweep every running session at
  shutdown — telling each one to abort, then waiting for the cleanup
  coroutine to record the partial assistant message back into the
  session store before the process exits.

Keyed by ``session_id`` (a string the client supplies; the backend
echoes it back on every event). Each entry holds:

* ``asyncio.Event`` cancel signal that the chat loop checks between
  chunks
* a ``Future`` that resolves when the loop finishes (cancelled or
  naturally) — the shutdown handler awaits this for bounded time
* the live ``assistant_message_id`` so cancellation can stamp a
  partial completion marker on it
"""

from __future__ import annotations

import asyncio
import logging

from mhc_desktop_backend.stream_state import SessionStream

logger = logging.getLogger("mhc_desktop_backend")


class StreamRegistry:
    """Process-local map ``session_id -> SessionStream``."""

    def __init__(self) -> None:
        self._streams: dict[str, SessionStream] = {}
        self._lock = asyncio.Lock()

    async def register(self, session_id: str) -> SessionStream:
        """Claim the slot. If another stream is already running for the
        same session, cancel it before claiming — the new request wins.
        """
        async with self._lock:
            existing = self._streams.get(session_id)
            if existing is not None:
                logger.warning(
                    "stream.replace session=%s — cancelling previous run", session_id
                )
                existing.cancel.set()
                existing.cancelled = True
                try:
                    await asyncio.wait_for(existing.done, timeout=2.0)
                except (TimeoutError, asyncio.CancelledError):
                    pass
            loop = asyncio.get_event_loop()
            stream = SessionStream(
                session_id=session_id,
                done=loop.create_future(),
            )
            self._streams[session_id] = stream
            return stream

    async def unregister(self, session_id: str) -> None:
        async with self._lock:
            self._streams.pop(session_id, None)

    def get(self, session_id: str) -> SessionStream | None:
        return self._streams.get(session_id)

    def active(self) -> list[str]:
        return list(self._streams.keys())

    async def cancel_all(self, timeout: float = 3.0) -> None:
        """Signal every running stream to stop. Used by the lifespan
        handler so the process exits cleanly. Returns after ``timeout``
        seconds regardless of whether the streams have actually torn
        down — the registry is best-effort.
        """
        async with self._lock:
            streams = list(self._streams.values())
        for s in streams:
            s.cancel.set()
            s.cancelled = True
            for t in s.tasks:
                t.cancel()
        # Wait for each done future in parallel
        if streams:
            await asyncio.wait(
                [s.done for s in streams],
                timeout=timeout,
                return_when=asyncio.ALL_COMPLETED,
            )
        async with self._lock:
            self._streams.clear()
