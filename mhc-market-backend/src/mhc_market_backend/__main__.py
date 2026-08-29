"""Run the market service: ``uv run python -m mhc_market_backend``.

Env: MHC_MARKET_HOST (127.0.0.1), MHC_MARKET_PORT (8766),
MHC_MARKET_DATA, MHC_MARKET_SECRET (required).
"""

from __future__ import annotations

import logging
import os

import uvicorn

from . import __version__

logger = logging.getLogger("mhc_market_backend")


def run() -> None:
    host = os.environ.get("MHC_MARKET_HOST", "127.0.0.1")
    port = int(os.environ.get("MHC_MARKET_PORT", "8766"))
    uvicorn.run(
        "mhc_market_backend.app:create_app",
        host=host,
        port=port,
        factory=True,
        log_level="info",
    )
    logger.info("mhc-market %s stopped", __version__)


if __name__ == "__main__":
    run()
