"""
ReelForge Reel URL Ingestion & Pipeline Orchestration Handler.

Detects Instagram Reel/Post URLs in messages, creates a processing job,
and orchestrates the full pipeline: download → transcribe → FFmpeg → AI caption
→ Telegram preview with verification keyboard.
"""

from __future__ import annotations

import re
from pathlib import Path

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import FSInputFile, Message

from app.bot.keyboards import build_verification_keyboard
from app.bot.states import VerificationStates
from app.models.job import JobStatus, ReelJob
from app.services import caption_ai, downloader, transcriber, video_editor
from app.utils.logger import get_job_logger
from app.utils.temp_manager import cleanup_job_dir, create_job_dir
from app.utils.time_parser import format_duration

router = Router(name="ingest")

# Regex pattern matching Instagram Reel/Post URLs
INSTAGRAM_URL_PATTERN = re.compile(
    r"https?://(?:www\.)?instagram\.com/(?:reel|p|reels)/[\w\-]+/?",
    re.IGNORECASE,
)


@router.message()
async def handle_message(message: Message, state: FSMContext) -> None:
    """
    Detect Instagram URLs in incoming messages and start the processing pipeline.

    Non-URL messages are ignored with a hint. Multiple URLs in a single
    message trigger only the first match.
    """
    if not message.text:
        return

    # Check if we're in an FSM state (let the verification handler deal with it)
    current_state = await state.get_state()
    if current_state is not None:
        return

    # Search for Instagram URLs
    match = INSTAGRAM_URL_PATTERN.search(message.text)
    if not match:
        # Only respond if the message looks like it was meant for the bot
        if message.chat.type == "private":
            await message.reply(
                "🔗 Send me an Instagram Reel or Post URL to get started!\n\n"
                "Example: `https://www.instagram.com/reel/ABC123/`\n\n"
                "Use /help for more info.",
                parse_mode="Markdown",
            )
        return

    url = match.group(0).rstrip("/")
    chat_id = message.chat.id

    # Initialize the job
    job = ReelJob(chat_id=chat_id, source_url=url)
    log = get_job_logger(job.job_id)

    log.info("New Reel job started", url=url, user_id=message.from_user.id if message.from_user else 0)

    # Send initial status message
    status_msg = await message.reply(
        f"🎬 **Processing Reel**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📎 `{url}`\n\n"
        f"⏳ Step 1/4: Downloading video...",
        parse_mode="Markdown",
    )
    job.status_message_id = status_msg.message_id

    try:
        await _run_pipeline(message, job, status_msg, state)
    except Exception as exc:
        log.error("Pipeline failed", error=str(exc), exc_info=True)
        job.status = JobStatus.FAILED

        await status_msg.edit_text(
            f"❌ **Processing Failed**\n\n"
            f"**Error:** `{type(exc).__name__}: {str(exc)[:200]}`\n\n"
            f"Job ID: `{job.job_id}`\n"
            f"Please try again or check the logs.",
            parse_mode="Markdown",
        )

        # Clean up on failure
        if job.work_dir:
            cleanup_job_dir(job.job_id)


async def _run_pipeline(
    message: Message,
    job: ReelJob,
    status_msg: Message,
    state: FSMContext,
) -> None:
    """
    Execute the full Reel processing pipeline.

    Stages:
        1. Download via yt-dlp
        2. Transcribe via faster-whisper
        3. Process video via FFmpeg
        4. Generate caption via LLM
        5. Send preview to Telegram with verification keyboard
    """
    log = get_job_logger(job.job_id)

    # ── Stage 1: Download ─────────────────────────
    job.status = JobStatus.DOWNLOADING
    job.work_dir = create_job_dir(job.job_id)

    raw_video, metadata = await downloader.download_reel(
        url=job.source_url,
        output_dir=job.work_dir,
        job_id=job.job_id,
    )

    job.raw_video_path = raw_video
    job.metadata = metadata

    log.info("Download complete", duration=f"{metadata.duration:.1f}s")

    # ── Stage 2: Transcribe ───────────────────────
    job.status = JobStatus.TRANSCRIBING
    await status_msg.edit_text(
        f"🎬 **Processing Reel**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📎 `{job.source_url}`\n"
        f"👤 Creator: @{metadata.uploader_id}\n"
        f"⏱ Duration: {format_duration(metadata.duration)}\n\n"
        f"✅ Step 1/4: Downloaded\n"
        f"⏳ Step 2/4: Transcribing speech...",
        parse_mode="Markdown",
    )

    srt_path, transcript = await transcriber.transcribe_audio(
        video_path=raw_video,
        output_dir=job.work_dir,
        job_id=job.job_id,
    )

    job.srt_path = srt_path
    job.transcript = transcript

    speech_status = f"({len(transcript.split())} words)" if transcript else "(no speech detected)"
    log.info("Transcription complete", speech_status=speech_status)

    # ── Stage 3: FFmpeg Processing ────────────────
    job.status = JobStatus.PROCESSING_VIDEO
    await status_msg.edit_text(
        f"🎬 **Processing Reel**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📎 `{job.source_url}`\n"
        f"👤 Creator: @{metadata.uploader_id}\n"
        f"⏱ Duration: {format_duration(metadata.duration)}\n\n"
        f"✅ Step 1/4: Downloaded\n"
        f"✅ Step 2/4: Transcribed {speech_status}\n"
        f"⏳ Step 3/4: Processing video (FFmpeg)...",
        parse_mode="Markdown",
    )

    output_mp4 = job.work_dir / "processed.mp4"
    await video_editor.process_reel(
        input_mp4=raw_video,
        srt_path=srt_path,
        output_mp4=output_mp4,
        job_id=job.job_id,
    )
    job.processed_video_path = output_mp4

    # Extract smart thumbnail
    thumbnail_path = job.work_dir / "thumbnail.jpg"
    await video_editor.extract_thumbnail(
        video_path=output_mp4,
        output_path=thumbnail_path,
        job_id=job.job_id,
    )
    job.thumbnail_path = thumbnail_path

    log.info("Video processing complete")

    # ── Stage 4: AI Caption Generation ────────────
    job.status = JobStatus.GENERATING_CAPTION
    await status_msg.edit_text(
        f"🎬 **Processing Reel**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📎 `{job.source_url}`\n"
        f"👤 Creator: @{metadata.uploader_id}\n"
        f"⏱ Duration: {format_duration(metadata.duration)}\n\n"
        f"✅ Step 1/4: Downloaded\n"
        f"✅ Step 2/4: Transcribed {speech_status}\n"
        f"✅ Step 3/4: Video processed\n"
        f"⏳ Step 4/4: Generating AI caption...",
        parse_mode="Markdown",
    )

    caption = await caption_ai.generate_caption(
        transcript=job.transcript,
        original_caption=metadata.description,
        original_creator=metadata.uploader_id,
        job_id=job.job_id,
    )
    job.caption = caption

    log.info("Caption generated", hook=caption.hook_line[:50])

    # ── Stage 5: Send Preview to Telegram ─────────
    job.status = JobStatus.AWAITING_APPROVAL

    # Delete the progress message
    await status_msg.delete()

    # Send the processed video
    video_file = FSInputFile(str(job.processed_video_path), filename=f"reel_{job.job_id}.mp4")
    thumb_file = FSInputFile(str(job.thumbnail_path)) if job.thumbnail_path and job.thumbnail_path.exists() else None

    preview_caption = _build_preview_caption(job)

    sent_video = await message.answer_video(
        video=video_file,
        thumbnail=thumb_file,
        caption=preview_caption,
        parse_mode="Markdown",
        reply_markup=build_verification_keyboard(job.job_id),
    )

    job.status_message_id = sent_video.message_id

    # Store job data in FSM state for the verification handlers
    await state.set_state(VerificationStates.waiting_approval)
    await state.update_data(job=job.model_dump(mode="json"))

    log.info("Preview sent — awaiting admin approval")


def _build_preview_caption(job: ReelJob) -> str:
    """Build the Telegram preview message caption."""
    caption = job.caption

    text = (
        f"🎬 **Reel Ready for Review**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 **Source:** @{job.metadata.uploader_id}\n"
        f"⏱ **Duration:** {format_duration(job.metadata.duration)}\n"
        f"🆔 **Job:** `{job.job_id}`\n\n"
        f"📝 **Generated Caption:**\n"
        f"───────────────────\n"
        f"{caption.full_caption}\n"
        f"───────────────────\n\n"
        f"Use the buttons below to approve, edit, or discard."
    )

    # Telegram caption limit is 1024 chars
    if len(text) > 1020:
        text = text[:1017] + "..."

    return text
