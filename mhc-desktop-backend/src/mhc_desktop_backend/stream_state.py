"""Per-session stream bookkeeping value-object.

``SessionStream`` is a dataclass holding the asyncio primitives the
chat loop uses to detect cancellation and the shutdown handler uses
to sweep in-flight streams. It is part of the kernel contract because
both :mod:`mhc_desktop_backend.api.chat` (which yields ``cancelled``
events when the user aborts) and any deploy-supplied
:class:`StreamRegistryProtocol` need to read / write its fields.

Moved out of :mod:`mhc_desktop_deploy.impls.file_stores.stream_registry`
when the registry's concrete implementation relocated to deploy.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SessionStream:
    session_id: str
    cancel: asyncio.Event = field(default_factory=asyncio.Event)
    done: asyncio.Future[None] = field(
        default_factory=lambda: asyncio.get_event_loop().create_future()
    )
    assistant_message_id: str = ""
    # Whether the client explicitly asked to cancel (vs the loop just
    # finishing). Set to True on /api/v1/chat/cancel; never reset.
    cancelled: bool = False
    # Background tasks the stream spawned (e.g. tool execution). The
    # shutdown handler cancels these too so the process doesn't hang on
    # an orphaned MCP subprocess call.
    tasks: list[asyncio.Task[Any]] = field(default_factory=list)


__all__ = ["SessionStream"]
