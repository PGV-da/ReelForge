"""
ReelForge Video Downloader Service.

Wraps yt-dlp for asynchronous downloading of Instagram Reels and posts,
extracting both the highest-quality MP4 stream and structured metadata.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Optional

from app.config import settings
from app.models.job import VideoMetadata
from app.utils.logger import get_job_logger


class DownloadError(Exception):
    """Raised when yt-dlp fails to download or extract video information."""


async def download_reel(
    url: str,
    output_dir: Path,
    job_id: str,
    cookies_file: Optional[Path] = None,
) -> tuple[Path, VideoMetadata]:
    """
    Download an Instagram Reel/Post video and extract its metadata.

    Uses yt-dlp under the hood, run in a thread to avoid blocking the
    async event loop. Attempts to select the best MP4 stream available.

    Args:
        url: Public Instagram Reel or Post URL.
        output_dir: Directory to save the downloaded video.
        job_id: Job identifier for contextual logging.
        cookies_file: Optional path to a cookies.txt file for authenticated access.

    Returns:
        Tuple of (path_to_downloaded_mp4, extracted_metadata).

    Raises:
        DownloadError: If download or metadata extraction fails.
    """
    log = get_job_logger(job_id)
    log.info("Starting download", url=url)

    output_path = output_dir / "source.mp4"

    # Build yt-dlp command using current Python environment
    cmd: list[str] = [
        sys.executable, "-m", "yt_dlp",
        "--no-warnings",
        "--no-playlist",
        "--format", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "--merge-output-format", "mp4",
        "--output", str(output_path),
        "--write-info-json",
        "--no-write-thumbnail",
        "--no-write-comments",
        "--socket-timeout", "30",
        "--retries", "3",
    ]

    # Add cookies support if configured
    effective_cookies = cookies_file or settings.cookies_file
    if effective_cookies and effective_cookies.exists():
        cmd.extend(["--cookies", str(effective_cookies)])
        log.debug("Using cookies file", path=str(effective_cookies))

    cmd.append(url)

    log.debug("Executing yt-dlp", command=" ".join(cmd))

    # Run yt-dlp asynchronously
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(output_dir),
    )

    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        error_msg = stderr.decode("utf-8", errors="replace").strip()
        log.error("yt-dlp failed", returncode=process.returncode, stderr=error_msg)
        raise DownloadError(f"yt-dlp download failed (code {process.returncode}): {error_msg}")

    # Verify the video file exists
    if not output_path.exists():
        # yt-dlp may have added a different extension; search for any mp4
        mp4_files = list(output_dir.glob("source.*"))
        if mp4_files:
            output_path = mp4_files[0]
        else:
            raise DownloadError("Downloaded video file not found in output directory")

    log.info("Download complete", path=str(output_path), size_mb=f"{output_path.stat().st_size / 1_048_576:.1f}")

    # Extract metadata from yt-dlp's info JSON
    metadata = await _extract_metadata(output_dir, job_id)

    return output_path, metadata


async def _extract_metadata(output_dir: Path, job_id: str) -> VideoMetadata:
    """
    Parse the .info.json file written by yt-dlp to extract video metadata.

    Args:
        output_dir: Directory containing the info JSON file.
        job_id: Job identifier for contextual logging.

    Returns:
        Populated VideoMetadata model.
    """
    log = get_job_logger(job_id)

    # Find the info json file
    info_files = list(output_dir.glob("*.info.json"))
    if not info_files:
        log.warning("No info.json found — using default metadata")
        return VideoMetadata()

    info_path = info_files[0]

    def _read_info() -> dict[str, Any]:
        with open(info_path, "r", encoding="utf-8") as f:
            return json.load(f)

    try:
        info = await asyncio.to_thread(_read_info)
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Failed to parse info.json", error=str(exc))
        return VideoMetadata()

    metadata = VideoMetadata(
        uploader_id=info.get("uploader_id") or info.get("channel") or info.get("uploader") or "unknown",
        description=info.get("description") or "",
        duration=float(info.get("duration") or 0),
        webpage_url=info.get("webpage_url") or "",
        width=int(info.get("width") or 0),
        height=int(info.get("height") or 0),
    )

    log.info(
        "Metadata extracted",
        uploader=metadata.uploader_id,
        duration=f"{metadata.duration:.1f}s",
        resolution=f"{metadata.width}x{metadata.height}",
    )

    return metadata
