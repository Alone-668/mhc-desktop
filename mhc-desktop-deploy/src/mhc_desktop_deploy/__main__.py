"""``python -m mhc_desktop_deploy`` entrypoint.

Wires the default file-backed stores + ``MockAuthProvider`` and
serves the FastAPI app. The canonical dev entrypoint now lives here
since the kernel whl ships clean (no inline file-backed stores).

Usage::

    uv run python -m mhc_desktop_deploy

Reads MHC_HOST / MHC_PORT / MHC_RELOAD from the environment (same
as the kernel's main module) so existing scripts that called
``python -m mhc_desktop_backend`` keep working if they point at
this module instead.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import uvicorn
from mhc_desktop_backend import __version__
from mhc_desktop_backend.config import load_config

from mhc_desktop_deploy._logging import build_log_config, make_log_formatter
from mhc_desktop_deploy.assemble import build_default_app


def run() -> None:
    cfg = load_config()

    log_level = os.getenv("MH_LOG_LEVEL", "INFO")
    root = logging.getLogger()
    root.setLevel(log_level)
    handler = logging.StreamHandler()
    handler.setFormatter(
        make_log_formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    root.addHandler(handler)
    logger = logging.getLogger("mhc_desktop_deploy")
    logger.info(
        "Starting mhc-desktop deploy %s on %s:%s", __version__, cfg.host, cfg.port
    )
    # ``build_default_app()`` returns a fully wired FastAPI instance.
    # We pass it via the import-string factory path so uvicorn's
    # ``reload`` option (which only works with strings) keeps
    # functioning in dev. The factory invokes ``build_default_app``
    # exactly once at boot — reload, when on, restarts the process
    # and re-runs the factory from scratch.
    uvicorn.run(
        "mhc_desktop_deploy.__main__:_factory",
        host=cfg.host,
        port=cfg.port,
        reload=os.getenv("MHC_RELOAD", "0") == "1",
        factory=True,
        log_level="info",
        log_config=build_log_config(log_level),
        loop="mhc_desktop_backend.main:_proactor_loop_factory",
    )


def _factory() -> Any:
    """uvicorn factory target — delegates to ``build_default_app``.

    Kept as a module-level function so the import-string reload
    mechanism (``reload=True``) works: uvicorn re-imports the module
    and re-calls this function on every file change.
    """
    return build_default_app()


if __name__ == "__main__":
    run()
