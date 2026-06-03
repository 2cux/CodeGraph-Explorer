"""Rotating file logger for hook events.

Writes to ``.codegraph/logs/hooks.log`` with 1 MB rotation limit
and 3 backup files.
"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

MAX_BYTES = 1_048_576  # 1 MB
BACKUP_COUNT = 3
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"

_logger: logging.Logger | None = None


def get_hook_logger(log_dir: Path) -> logging.Logger:
    """Return (or create) the rotating hook logger.

    The logger is a singleton — subsequent calls return the same instance
    (though handlers are refreshed if the log dir changes).

    Args:
        log_dir: Path to ``.codegraph/logs/`` directory.

    Returns:
        Configured ``logging.Logger`` instance named ``"codegraph.hook"``.
    """
    global _logger

    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "hooks.log"

    if _logger is None:
        _logger = logging.getLogger("codegraph.hook")
        _logger.setLevel(logging.INFO)
        _logger.propagate = False  # Don't leak to root logger

    # Replace handler if the path changed (e.g. different project root)
    _logger.handlers.clear()

    handler = RotatingFileHandler(
        str(log_path),
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)
    handler.setFormatter(formatter)
    _logger.addHandler(handler)

    return _logger
