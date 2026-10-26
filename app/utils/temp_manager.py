"""
ReelForge Temporary Directory Manager.

Provides async-safe context management for per-job isolated working directories.
Ensures cleanup occurs on success, rejection, or failure, preventing disk leaks.
"""

from __future__ import annotations

import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from loguru import logger

from app.config import settings


def create_job_dir(job_id: str) -> Path:
    """
    Create an isolated temporary directory for a specific job.

    Args:
        job_id: Unique identifier for the processing job.

    Returns:
        Path to the created directory: ``{TEMP_BASE_DIR}/{job_id}/``
    """
    job_dir = settings.temp_base_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Created job directory", job_id=job_id, path=str(job_dir))
    return job_dir


def cleanup_job_dir(job_id: str) -> None:
    """
    Remove all files and the directory for a completed or discarded job.

    Args:
        job_id: Unique identifier for the processing job.
    """
    job_dir = settings.temp_base_dir / job_id
    if job_dir.exists():
        shutil.rmtree(job_dir, ignore_errors=True)
        logger.info("Cleaned up job directory", job_id=job_id, path=str(job_dir))
    else:
        logger.debug("Job directory already cleaned", job_id=job_id)


@asynccontextmanager
async def managed_job_dir(job_id: str, auto_cleanup: bool = True) -> AsyncGenerator[Path, None]:
    """
    Async context manager that creates a job directory on entry and optionally
    cleans it up on exit. Cleanup is always attempted on exceptions.

    Args:
        job_id: Unique identifier for the processing job.
        auto_cleanup: If True, remove the directory when the context exits normally.
                      Always cleaned up on exceptions regardless of this flag.

    Yields:
        Path to the job's isolated temporary directory.

    Example::

        async with managed_job_dir("abc123") as work_dir:
            raw_video = work_dir / "source.mp4"
            # ... download, process, upload ...
        # Directory is automatically cleaned up after the block
    """
    job_dir = create_job_dir(job_id)
    try:
        yield job_dir
    except Exception:
        logger.warning("Job failed — cleaning up directory", job_id=job_id)
        cleanup_job_dir(job_id)
        raise
    else:
        if auto_cleanup:
            cleanup_job_dir(job_id)
