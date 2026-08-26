"""Runtime configuration for mhc-desktop-backend.

Read once at startup; immutable. All fields are tunable through environment
variables (prefix ``MHC_``); see ``main.py`` for the entry point.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    debug: bool = True
    host: str = "127.0.0.1"
    port: int = 8765


def load_config() -> Config:
    """Build :class:`Config` from environment variables.

    Defaults match ``scripts/dev-mhc-desktop.sh`` so the dev loop works out
    of the box; everything is overridable per process.
    """
    return Config(
        debug=os.getenv("MHC_DEBUG", "1") == "1",
        host=os.getenv("MHC_HOST", "127.0.0.1"),
        port=int(os.getenv("MHC_PORT", "8765")),
    )
