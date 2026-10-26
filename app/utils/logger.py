"""
ReelForge Logging Configuration.

Sets up Loguru with contextual logging, structured formatting,
and per-job context binding. All modules import ``logger`` from here.
"""

from __future__ import annotations

import sys

from loguru import logger

# Remove default handler to reconfigure
logger.remove()

# ── Console Handler (Development & Container stdout) ──
logger.add(
    sys.stderr,
    format=(
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "{extra[job_id]} | "
        "<level>{message}</level>"
    ),
    level="DEBUG",
    colorize=True,
    backtrace=True,
    diagnose=True,
    filter=lambda record: record["extra"].setdefault("job_id", "system"),
)

# ── File Handler (Persistent Logs for Production) ──
logger.add(
    "logs/reelforge_{time:YYYY-MM-DD}.log",
    format=(
        "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
        "{level: <8} | "
        "{name}:{function}:{line} | "
        "{extra[job_id]} | "
        "{message}"
    ),
    level="INFO",
    rotation="50 MB",
    retention="14 days",
    compression="gz",
    encoding="utf-8",
    filter=lambda record: record["extra"].setdefault("job_id", "system"),
)


def get_job_logger(job_id: str) -> logger.__class__:  # type: ignore[name-defined]
    """
    Create a context-bound logger for a specific job.

    All log entries from the returned logger will include the ``job_id``
    in their output for easy filtering and tracing.

    Args:
        job_id: Unique identifier for the processing job.

    Returns:
        A Loguru logger instance bound with the job's context.

    Example::

        log = get_job_logger("abc123")
        log.info("Starting download")
        # Output: ... | abc123 | Starting download
    """
    return logger.bind(job_id=job_id)


# Re-export logger for direct imports
__all__ = ["logger", "get_job_logger"]
