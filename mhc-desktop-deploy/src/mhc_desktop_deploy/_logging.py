"""Shanghai-time logging formatter for the deploy shell.

Kept in its own module so uvicorn's reload can re-import the
formatter function (``mhc_desktop_deploy.__main__:make_log_formatter``
fails because ``__main__`` is special-cased by Python and can't
be imported under that name). The kernel has its own copy in
:mod:`mhc_desktop_backend.main`; we re-implement it here rather
than cross-importing to keep the deploy whl's dependency on the
kernel one-directional (deploy depends on kernel, never the other
way).
"""

from __future__ import annotations

import logging
import time

_SHANGHAI_OFFSET = 8 * 3600  # seconds


def make_log_formatter(fmt: str) -> logging.Formatter:
    """Build a :class:`logging.Formatter` whose ``%(asctime)s`` is
    fixed to Asia/Shanghai.

    Asia/Shanghai never observes DST — a fixed +08:00 offset is
    exact and can't drift with the build machine's or the user
    machine's local timezone.
    """
    formatter = logging.Formatter(fmt)
    formatter.converter = lambda t: time.gmtime(t + _SHANGHAI_OFFSET)  # type: ignore[assignment]
    return formatter


def build_log_config(level: str = "INFO") -> dict:
    """Return the uvicorn log-config dict using the importable path
    to ``make_log_formatter`` (so reload works)."""
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "shanghai": {
                "()": "mhc_desktop_deploy._logging.make_log_formatter",
                "fmt": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            },
        },
        "handlers": {
            "stderr": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stderr",
                "formatter": "shanghai",
            },
        },
        "root": {
            "handlers": ["stderr"],
            "level": level,
        },
        "loggers": {
            "uvicorn": {"handlers": ["stderr"], "level": "INFO", "propagate": False},
            "uvicorn.error": {
                "handlers": ["stderr"],
                "level": "INFO",
                "propagate": False,
            },
            "uvicorn.access": {
                "handlers": ["stderr"],
                "level": "INFO",
                "propagate": False,
            },
        },
    }


__all__ = ["make_log_formatter", "build_log_config"]
