"""File logging for the market service.

Logs go to ``<data_root>/logs/market.log`` (daily rotation, 14 days
kept) in addition to stderr, so a broken deployment can be diagnosed
by handing the log directory to a coding agent. Every line carries
Shanghai time (fixed UTC+8, like the kernel's formatter) so log files
from different services sort together.
"""

from __future__ import annotations

import logging
import logging.handlers
import time
from pathlib import Path

_SHANGHAI_OFFSET = 8 * 3600

_FMT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def make_log_formatter() -> logging.Formatter:
    fmt = logging.Formatter(_FMT)
    fmt.converter = lambda t: time.gmtime(t + _SHANGHAI_OFFSET)  # type: ignore[assignment]
    return fmt


def setup_file_logging(data_root: Path, logger_names: tuple[str, ...]) -> Path:
    """Attach a daily-rotating file handler to the given loggers.

    Returns the log directory so callers can surface it in /health.
    """
    log_dir = data_root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler: logging.Handler = logging.handlers.TimedRotatingFileHandler(
        log_dir / "market.log",
        when="midnight",
        backupCount=14,
        encoding="utf-8",
    )
    handler.setFormatter(make_log_formatter())
    for name in logger_names:
        lg = logging.getLogger(name)
        lg.addHandler(handler)
        lg.setLevel(logging.INFO)
    return log_dir


__all__ = ["make_log_formatter", "setup_file_logging"]
