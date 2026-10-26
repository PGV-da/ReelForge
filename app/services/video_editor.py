"""
ReelForge FFmpeg Video, Audio & Thumbnail Transformation Pipeline.

Builds and executes FFmpeg commands asynchronously to apply originality
transforms: metadata stripping, resolution normalization, speed shift,
subtitle burn-in, watermark overlay, audio EQ fingerprint alteration,
and smart thumbnail extraction.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Optional

from app.config import settings
from app.utils.logger import get_job_logger


class VideoProcessingError(Exception):
    """Raised when FFmpeg processing fails."""


def _escape_ffmpeg_path(path: Path) -> str:
    """
    Escape a file path for use in FFmpeg filter expressions.

    FFmpeg's subtitle filter requires special escaping for colons,
    backslashes, and single quotes in file paths.

    Args:
        path: File path to escape.

    Returns:
        Escaped path string safe for FFmpeg filter graphs.
    """
    s = str(path).replace("\\", "/")
    s = s.replace(":", "\\:")
    s = s.replace("'", "'\\\\\\''")
    return s


async def _run_ffmpeg(cmd: list[str], job_id: str, description: str) -> None:
    """
    Execute an FFmpeg command asynchronously with logging.

    Args:
        cmd: FFmpeg command arguments list.
        job_id: Job identifier for logging.
        description: Human-readable description of the operation.

    Raises:
        VideoProcessingError: If FFmpeg returns a non-zero exit code.
    """
    log = get_job_logger(job_id)
    log.debug(f"FFmpeg [{description}]", command=" ".join(cmd))

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    _, stderr = await process.communicate()

    if process.returncode != 0:
        error_msg = stderr.decode("utf-8", errors="replace")
        # Extract the most relevant error line
        error_lines = [
            line for line in error_msg.split("\n")
            if "error" in line.lower() or "invalid" in line.lower()
        ]
        summary = error_lines[-1] if error_lines else error_msg[-500:]
        log.error(f"FFmpeg [{description}] failed", returncode=process.returncode, error=summary)
        raise VideoProcessingError(f"FFmpeg {description} failed (code {process.returncode}): {summary}")

    log.info(f"FFmpeg [{description}] complete")


async def process_reel(
    input_mp4: Path,
    srt_path: Optional[Path],
    output_mp4: Path,
    watermark: Optional[str] = None,
    job_id: str = "unknown",
) -> Path:
    """
    Apply the full originality transformation pipeline to a downloaded Reel.

    Performs the following in a single FFmpeg pass:
    - Strips all source container metadata
    - Scales and center-crops to 1080x1920 (9:16) with ~3% zoom
    - Applies a +2% speed shift (video PTS and audio atempo)
    - Burns subtitles into the lower-middle safe zone (if provided)
    - Overlays a configurable username watermark at top-center
    - Applies an imperceptible audio EQ fingerprint alteration
    - Encodes with libx264 (CRF 22, fast preset, yuv420p) and AAC audio

    Args:
        input_mp4: Path to the source video file.
        srt_path: Path to the .srt subtitle file (None to skip subtitle burn-in).
        output_mp4: Desired output path for the processed video.
        watermark: Watermark text (defaults to config value).
        job_id: Job identifier for logging.

    Returns:
        Path to the processed output video.

    Raises:
        VideoProcessingError: If FFmpeg processing fails.
    """
    log = get_job_logger(job_id)
    effective_watermark = watermark or settings.watermark_text

    # Resolve font path
    font_path = settings.font_path
    if not font_path.is_absolute():
        font_path = Path.cwd() / font_path

    # ── Build Video Filter Chain ──────────────────
    video_filters: list[str] = [
        # Speed shift: +2% faster (1/1.02 ≈ 0.9803)
        "setpts=0.9803*PTS",
        # Scale up slightly (~3% zoom) then center-crop to exact 1080x1920
        "scale=1112:1978:force_original_aspect_ratio=increase",
        "crop=1080:1920",
        # Normalize framerate
        "fps=30",
    ]

    # Burn subtitles if SRT exists and has content
    if srt_path and srt_path.exists() and srt_path.stat().st_size > 0:
        escaped_srt = _escape_ffmpeg_path(srt_path)
        escaped_font_dir = _escape_ffmpeg_path(font_path.parent)

        subtitle_style = (
            "Fontname=Montserrat,"
            "Fontsize=18,"
            "PrimaryColour=&H00FFFFFF,"
            "OutlineColour=&H00000000,"
            "BackColour=&H80000000,"
            "Bold=1,"
            "BorderStyle=3,"
            "Outline=2,"
            "Alignment=2,"
            "MarginV=75"
        )

        video_filters.append(
            f"subtitles='{escaped_srt}':fontsdir='{escaped_font_dir}':force_style='{subtitle_style}'"
        )
        log.info("Subtitles will be burned in", srt_path=str(srt_path))
    else:
        log.info("No subtitles to burn — skipping subtitle overlay")

    # Watermark overlay via drawtext
    escaped_font = _escape_ffmpeg_path(font_path)
    video_filters.append(
        f"drawtext=text='{effective_watermark}'"
        f":fontfile='{escaped_font}'"
        f":fontsize=36"
        f":fontcolor=white@0.85"
        f":x=(w-text_w)/2"
        f":y=110"
        f":box=1"
        f":boxcolor=black@0.4"
        f":boxborderw=8"
    )

    video_filter_chain = ",".join(video_filters)

    # ── Build Audio Filter Chain ──────────────────
    audio_filters: list[str] = [
        # Match the +2% video speed shift
        "atempo=1.02",
        # Imperceptible EQ fingerprint alteration
        "highpass=f=65",
        "lowpass=f=15500",
        "equalizer=f=3000:width_type=h:width=200:g=1.5",
    ]
    audio_filter_chain = ",".join(audio_filters)

    # ── Assemble Complete FFmpeg Command ──────────
    cmd: list[str] = [
        "ffmpeg", "-y",
        "-i", str(input_mp4),
        # Video filters
        "-vf", video_filter_chain,
        # Audio filters
        "-af", audio_filter_chain,
        # Video encoding
        "-c:v", "libx264",
        "-crf", "22",
        "-preset", "fast",
        "-pix_fmt", "yuv420p",
        "-profile:v", "high",
        "-level", "4.1",
        # Audio encoding
        "-c:a", "aac",
        "-b:a", "128k",
        "-ar", "48000",
        "-ac", "2",
        # Container options
        "-map_metadata", "-1",          # Strip all source metadata
        "-movflags", "+faststart",      # Optimize for streaming
        "-max_muxing_queue_size", "1024",
        str(output_mp4),
    ]

    await _run_ffmpeg(cmd, job_id, "reel processing")

    # Verify output
    if not output_mp4.exists():
        raise VideoProcessingError("Processed video file was not created")

    output_size_mb = output_mp4.stat().st_size / 1_048_576
    log.info(
        "Reel processed successfully",
        output=str(output_mp4),
        size_mb=f"{output_size_mb:.1f}",
    )

    return output_mp4


async def extract_thumbnail(
    video_path: Path,
    output_path: Path,
    job_id: str,
    timestamp_ms: Optional[int] = None,
) -> Path:
    """
    Extract a high-quality thumbnail from the video.

    Uses FFmpeg's ``thumbnail=150`` filter to find the sharpest frame,
    or extracts a frame at a specific timestamp if provided.

    Args:
        video_path: Path to the video file.
        output_path: Desired output path for the thumbnail JPEG.
        job_id: Job identifier for logging.
        timestamp_ms: Optional timestamp in milliseconds to extract a specific frame.
                      If None, uses FFmpeg's smart sharpest-frame detection.

    Returns:
        Path to the extracted thumbnail image.

    Raises:
        VideoProcessingError: If thumbnail extraction fails.
    """
    log = get_job_logger(job_id)

    if timestamp_ms is not None:
        # Extract frame at specific timestamp
        seconds = timestamp_ms / 1000.0
        cmd = [
            "ffmpeg", "-y",
            "-ss", f"{seconds:.3f}",
            "-i", str(video_path),
            "-vframes", "1",
            "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:-1:-1:black",
            "-q:v", "2",
            str(output_path),
        ]
        description = f"thumbnail at {seconds:.1f}s"
    else:
        # Smart thumbnail: find sharpest frame
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-vf", "thumbnail=150,scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:-1:-1:black",
            "-frames:v", "1",
            "-q:v", "2",
            str(output_path),
        ]
        description = "smart thumbnail (sharpest frame)"

    await _run_ffmpeg(cmd, job_id, description)

    if not output_path.exists():
        raise VideoProcessingError("Thumbnail file was not created")

    log.info("Thumbnail extracted", path=str(output_path))
    return output_path


async def extract_thumbnail_at_timestamp(
    video_path: Path,
    output_dir: Path,
    job_id: str,
    timestamp_ms: int,
) -> Path:
    """
    Convenience wrapper to extract a thumbnail at a specific timestamp.

    Args:
        video_path: Path to the video file.
        output_dir: Directory to write the thumbnail.
        job_id: Job identifier for logging.
        timestamp_ms: Timestamp in milliseconds.

    Returns:
        Path to the extracted thumbnail.
    """
    output_path = output_dir / "thumbnail.jpg"
    return await extract_thumbnail(video_path, output_path, job_id, timestamp_ms)


async def get_video_duration_ms(video_path: Path) -> int:
    """
    Get the duration of a video file in milliseconds using FFprobe.

    Args:
        video_path: Path to the video file.

    Returns:
        Duration in milliseconds.
    """
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path),
    ]

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    stdout, _ = await process.communicate()

    try:
        duration_sec = float(stdout.decode().strip())
        return int(duration_sec * 1000)
    except (ValueError, AttributeError):
        return 0
