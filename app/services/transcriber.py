"""
ReelForge Speech-to-Text & Subtitle Service.

Uses faster-whisper for local audio transcription, producing both a
formatted .srt subtitle file (optimized for vertical video readability)
and a plain-text transcript for the LLM caption generator.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

from app.config import settings
from app.utils.logger import get_job_logger
from app.utils.time_parser import seconds_to_srt_timestamp


class TranscriptionError(Exception):
    """Raised when audio extraction or transcription fails."""


# Maximum words per subtitle line for vertical video readability
MAX_WORDS_PER_LINE = 6


async def extract_audio(video_path: Path, output_dir: Path, job_id: str) -> Path:
    """
    Extract the audio track from a video file using FFmpeg.

    Args:
        video_path: Path to the source video file.
        output_dir: Directory to write the extracted audio.
        job_id: Job identifier for logging.

    Returns:
        Path to the extracted WAV file.

    Raises:
        TranscriptionError: If FFmpeg fails to extract audio.
    """
    log = get_job_logger(job_id)
    audio_path = output_dir / "audio.wav"

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        str(audio_path),
    ]

    log.debug("Extracting audio track")
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()

    if process.returncode != 0:
        error_msg = stderr.decode("utf-8", errors="replace")
        log.error("Audio extraction failed", stderr=error_msg)
        raise TranscriptionError(f"FFmpeg audio extraction failed: {error_msg}")

    log.info("Audio extracted", path=str(audio_path))
    return audio_path


async def transcribe_audio(
    video_path: Path,
    output_dir: Path,
    job_id: str,
    model_size: Optional[str] = None,
) -> tuple[Optional[Path], str]:
    """
    Transcribe speech from a video's audio track using faster-whisper.

    Extracts audio via FFmpeg, runs whisper inference in a thread pool,
    generates a formatted .srt file, and returns the plain-text transcript.

    Gracefully handles music-only/no-speech reels by returning None for the
    srt_path and an empty transcript string.

    Args:
        video_path: Path to the source video file.
        output_dir: Directory to write output files.
        job_id: Job identifier for logging.
        model_size: Whisper model to use (defaults to config value).

    Returns:
        Tuple of (srt_file_path_or_None, plain_text_transcript).
        srt_path is None if no speech was detected.

    Raises:
        TranscriptionError: If audio extraction or transcription fails critically.
    """
    log = get_job_logger(job_id)
    effective_model = model_size or settings.whisper_model_size

    # Step 1: Extract audio
    audio_path = await extract_audio(video_path, output_dir, job_id)

    # Step 2: Run faster-whisper in a thread (it's CPU/GPU-bound)
    log.info("Starting transcription", model=effective_model)

    def _run_whisper() -> list[dict]:
        """Run whisper inference synchronously in a worker thread."""
        from faster_whisper import WhisperModel

        # Detect CUDA availability
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
        compute_type = "float16" if device == "cuda" else "int8"

        log.debug("Loading whisper model", device=device, compute_type=compute_type)

        model = WhisperModel(
            effective_model,
            device=device,
            compute_type=compute_type,
        )

        segments_iter, info = model.transcribe(
            str(audio_path),
            beam_size=5,
            word_timestamps=True,
            vad_filter=True,
            vad_parameters=dict(
                min_silence_duration_ms=500,
                speech_pad_ms=200,
            ),
        )

        log.info(
            "Transcription info",
            language=info.language,
            language_probability=f"{info.language_probability:.2%}",
            duration=f"{info.duration:.1f}s",
        )

        # Collect all word-level timestamps
        words = []
        for segment in segments_iter:
            if segment.words:
                for word in segment.words:
                    words.append({
                        "word": word.word.strip(),
                        "start": word.start,
                        "end": word.end,
                    })

        return words

    try:
        words = await asyncio.to_thread(_run_whisper)
    except Exception as exc:
        # Try without torch dependency
        log.warning("Whisper with torch detection failed, trying CPU fallback", error=str(exc))
        try:
            words = await asyncio.to_thread(_run_whisper_fallback, audio_path, effective_model, log)
        except Exception as fallback_exc:
            log.error("Transcription failed completely", error=str(fallback_exc))
            raise TranscriptionError(f"Transcription failed: {fallback_exc}") from fallback_exc

    # Step 3: Handle no-speech case
    if not words:
        log.info("No speech detected — skipping subtitle generation")
        return None, ""

    # Step 4: Group words into short subtitle lines
    subtitle_groups = _group_words_into_lines(words)

    # Step 5: Generate SRT file
    srt_path = output_dir / "subtitles.srt"
    srt_content = _build_srt(subtitle_groups)
    srt_path.write_text(srt_content, encoding="utf-8")

    # Step 6: Build plain-text transcript
    transcript = " ".join(w["word"] for w in words)

    log.info(
        "Transcription complete",
        segments=len(subtitle_groups),
        words=len(words),
        srt_path=str(srt_path),
    )

    return srt_path, transcript


def _run_whisper_fallback(audio_path: Path, model_size: str, log: object) -> list[dict]:
    """Fallback whisper runner without torch dependency check."""
    from faster_whisper import WhisperModel

    model = WhisperModel(model_size, device="cpu", compute_type="int8")

    segments_iter, info = model.transcribe(
        str(audio_path),
        beam_size=5,
        word_timestamps=True,
        vad_filter=True,
    )

    words = []
    for segment in segments_iter:
        if segment.words:
            for word in segment.words:
                words.append({
                    "word": word.word.strip(),
                    "start": word.start,
                    "end": word.end,
                })

    return words


def _group_words_into_lines(
    words: list[dict],
    max_words: int = MAX_WORDS_PER_LINE,
) -> list[dict]:
    """
    Group word-level timestamps into subtitle segments with short,
    punchy lines optimized for vertical video readability.

    Args:
        words: List of word dicts with 'word', 'start', 'end' keys.
        max_words: Maximum words per subtitle segment.

    Returns:
        List of segment dicts with 'text', 'start', 'end' keys.
    """
    groups: list[dict] = []
    current_words: list[str] = []
    group_start: float = 0.0
    group_end: float = 0.0

    for i, word_info in enumerate(words):
        if not current_words:
            group_start = word_info["start"]

        current_words.append(word_info["word"])
        group_end = word_info["end"]

        # Flush the group if we've hit the word limit or it's the last word
        if len(current_words) >= max_words or i == len(words) - 1:
            groups.append({
                "text": " ".join(current_words),
                "start": group_start,
                "end": group_end,
            })
            current_words = []

    return groups


def _build_srt(groups: list[dict]) -> str:
    """
    Build an SRT-formatted subtitle string from grouped segments.

    Args:
        groups: List of segment dicts with 'text', 'start', 'end' keys.

    Returns:
        Complete SRT file content as a string.
    """
    lines: list[str] = []

    for i, group in enumerate(groups, start=1):
        start_ts = seconds_to_srt_timestamp(group["start"])
        end_ts = seconds_to_srt_timestamp(group["end"])
        lines.append(str(i))
        lines.append(f"{start_ts} --> {end_ts}")
        lines.append(group["text"])
        lines.append("")  # Blank line separator

    return "\n".join(lines)
