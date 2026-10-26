"""
ReelForge Verification & Callback Query Handlers.

Handles all interactive inline keyboard button presses for the Reel
verification workflow: Approve, Edit Caption, Regenerate, Set Thumbnail,
Discard, and Cancel Edit operations.
"""

from __future__ import annotations

from pathlib import Path

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, Message

from app.bot.keyboards import (
    build_cancel_keyboard,
    build_publishing_keyboard,
    build_verification_keyboard,
)
from app.bot.states import VerificationStates
from app.config import settings
from app.models.job import GeneratedCaption, JobStatus, ReelJob, VideoMetadata
from app.services import caption_ai, video_editor
from app.services.instagram_api import InstagramPublisher
from app.utils.logger import get_job_logger
from app.utils.temp_manager import cleanup_job_dir
from app.utils.time_parser import format_duration, parse_to_ms

router = Router(name="verification")


# ── Helper: Reconstruct Job from FSM State ────────

async def _get_job(state: FSMContext) -> ReelJob | None:
    """Reconstruct the ReelJob from FSM state data."""
    data = await state.get_data()
    job_data = data.get("job")
    if not job_data:
        return None
    return ReelJob(**job_data)


async def _save_job(state: FSMContext, job: ReelJob) -> None:
    """Save the updated ReelJob back to FSM state."""
    await state.update_data(job=job.model_dump(mode="json"))


# ── Approve & Publish ────────────────────────────

@router.callback_query(F.data.startswith("approve:"))
async def on_approve(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle the Approve & Publish button press."""
    job = await _get_job(state)
    if not job:
        await callback.answer("⚠️ Job not found. Please start a new one.", show_alert=True)
        return

    log = get_job_logger(job.job_id)

    # ── Branch: Local workflow when Instagram upload is disabled ──
    if not settings.ig_enabled:
        log.info("Admin approved — completing locally (IG upload disabled)")
        job.status = JobStatus.APPROVED
        await _save_job(state, job)

        await callback.answer("✅ Approved! Delivering final files...")

        if callback.message:
            await callback.message.edit_reply_markup(reply_markup=None)

            caption_block = job.effective_caption
            completion_msg = (
                f"✅ **Reel Approved & Saved!**\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"🆔 **Job:** `{job.job_id}`\n"
                f"👤 **Source:** @{job.metadata.uploader_id}\n\n"
                f"📝 **Final Caption (Tap & copy):**\n"
                f"```text\n{caption_block}\n```\n\n"
                f"💾 The processed HD video has been delivered below. You can save and post it directly!\n"
                f"_(Instagram auto-publishing is currently disabled)_"
            )

            # Send document for lossless original quality download
            video_path = Path(job.processed_video_path) if job.processed_video_path else None
            if video_path and video_path.exists():
                doc_file = FSInputFile(
                    str(video_path),
                    filename=f"reelforge_{job.metadata.uploader_id}_{job.job_id[:8]}.mp4",
                )
                await callback.message.reply_document(
                    document=doc_file,
                    caption=completion_msg,
                    parse_mode="Markdown",
                )
            else:
                await callback.message.reply(completion_msg, parse_mode="Markdown")

        cleanup_job_dir(job.job_id)
        await state.clear()
        return

    # ── Branch: Publish to Instagram via Meta Graph API ──
    log.info("Admin approved — starting Instagram publish")

    # Prevent double-clicks
    job.status = JobStatus.PUBLISHING
    await _save_job(state, job)
    await state.set_state(VerificationStates.publishing)

    # Update the keyboard to show publishing progress
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=build_publishing_keyboard())

    await callback.answer("🚀 Publishing to Instagram...")

    try:
        publisher = InstagramPublisher()
        container_id, permalink = await publisher.publish_reel(
            video_path=Path(job.processed_video_path) if job.processed_video_path else Path(""),
            caption=job.effective_caption,
            thumb_offset_ms=job.thumb_offset_ms,
            job_id=job.job_id,
        )

        job.ig_container_id = container_id
        job.ig_permalink = permalink
        job.status = JobStatus.PUBLISHED

        # Send success message
        if callback.message:
            await callback.message.edit_caption(
                caption=(
                    f"✅ **Published Successfully!**\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"🔗 [View on Instagram]({permalink})\n"
                    f"🆔 Job: `{job.job_id}`\n"
                    f"👤 Source: @{job.metadata.uploader_id}\n\n"
                    f"The reel is now live on your Instagram account! 🎉"
                ),
                parse_mode="Markdown",
                reply_markup=None,
            )

        log.info("Reel published!", permalink=permalink)

    except Exception as exc:
        log.error("Publishing failed", error=str(exc), exc_info=True)
        job.status = JobStatus.FAILED

        if callback.message:
            await callback.message.edit_caption(
                caption=(
                    f"❌ **Publishing Failed**\n\n"
                    f"**Error:** `{type(exc).__name__}: {str(exc)[:200]}`\n\n"
                    f"Job ID: `{job.job_id}`\n"
                    f"Check your token with /token\\_health and try again."
                ),
                parse_mode="Markdown",
                reply_markup=build_verification_keyboard(job.job_id),
            )
            # Reset state to allow retry
            await state.set_state(VerificationStates.waiting_approval)
            await _save_job(state, job)
            return

    # Clean up temp files
    cleanup_job_dir(job.job_id)
    await state.clear()


# ── Edit Caption ──────────────────────────────────

@router.callback_query(F.data.startswith("edit_caption:"))
async def on_edit_caption(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle the Edit Caption button — enter FSM state waiting for text."""
    job = await _get_job(state)
    if not job:
        await callback.answer("⚠️ Job not found.", show_alert=True)
        return

    log = get_job_logger(job.job_id)
    log.info("Admin entering caption edit mode")

    await state.set_state(VerificationStates.editing_caption)
    await callback.answer("✏️ Send your new caption text")

    if callback.message:
        await callback.message.reply(
            "✏️ **Edit Caption**\n\n"
            "Send your new caption text as a message.\n"
            "Include hashtags, emojis, and line breaks as desired.\n\n"
            "_The entire message will be used as the Instagram caption._",
            parse_mode="Markdown",
            reply_markup=build_cancel_keyboard(job.job_id),
        )


@router.message(VerificationStates.editing_caption)
async def receive_edited_caption(message: Message, state: FSMContext) -> None:
    """Receive the user's custom caption text and update the job."""
    job = await _get_job(state)
    if not job:
        await message.reply("⚠️ No active job. Send a new Reel URL to start.")
        await state.clear()
        return

    if not message.text:
        await message.reply("⚠️ Please send text for the caption.")
        return

    log = get_job_logger(job.job_id)
    job.custom_caption = message.text
    await _save_job(state, job)

    log.info("Caption updated by admin", length=len(message.text))

    # Re-send the video preview with updated caption
    await state.set_state(VerificationStates.waiting_approval)

    preview_text = (
        f"🎬 **Reel Ready for Review** (Caption Updated)\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 **Source:** @{job.metadata.uploader_id}\n"
        f"🆔 **Job:** `{job.job_id}`\n\n"
        f"📝 **Updated Caption:**\n"
        f"───────────────────\n"
        f"{job.effective_caption}\n"
        f"───────────────────\n\n"
        f"Use the buttons below to approve, edit, or discard."
    )

    if len(preview_text) > 1020:
        preview_text = preview_text[:1017] + "..."

    await message.reply(
        preview_text,
        parse_mode="Markdown",
        reply_markup=build_verification_keyboard(job.job_id),
    )


# ── Regenerate Caption ────────────────────────────

@router.callback_query(F.data.startswith("regenerate:"))
async def on_regenerate_caption(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle the Regenerate Caption button — re-run the LLM with fresh angle."""
    job = await _get_job(state)
    if not job:
        await callback.answer("⚠️ Job not found.", show_alert=True)
        return

    log = get_job_logger(job.job_id)
    log.info("Admin requested caption regeneration")

    await callback.answer("🔄 Regenerating caption...")

    try:
        new_caption = await caption_ai.generate_caption(
            transcript=job.transcript,
            original_caption=job.metadata.description,
            original_creator=job.metadata.uploader_id,
            job_id=job.job_id,
        )

        job.caption = new_caption
        job.custom_caption = None  # Clear any previous custom edit
        await _save_job(state, job)

        log.info("Caption regenerated", hook=new_caption.hook_line[:50])

        # Update the preview message
        preview_text = (
            f"🎬 **Reel Ready for Review** (Caption Regenerated 🔄)\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 **Source:** @{job.metadata.uploader_id}\n"
            f"🆔 **Job:** `{job.job_id}`\n\n"
            f"📝 **New Caption:**\n"
            f"───────────────────\n"
            f"{new_caption.full_caption}\n"
            f"───────────────────\n\n"
            f"Use the buttons below to approve, edit, or discard."
        )

        if len(preview_text) > 1020:
            preview_text = preview_text[:1017] + "..."

        if callback.message:
            await callback.message.edit_caption(
                caption=preview_text,
                parse_mode="Markdown",
                reply_markup=build_verification_keyboard(job.job_id),
            )

    except Exception as exc:
        log.error("Caption regeneration failed", error=str(exc))
        await callback.answer(
            f"❌ Regeneration failed: {str(exc)[:100]}",
            show_alert=True,
        )


# ── Set Thumbnail Timestamp ──────────────────────

@router.callback_query(F.data.startswith("set_thumb:"))
async def on_set_thumbnail(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle the Set Thumbnail button — enter FSM state waiting for timestamp."""
    job = await _get_job(state)
    if not job:
        await callback.answer("⚠️ Job not found.", show_alert=True)
        return

    log = get_job_logger(job.job_id)
    log.info("Admin entering thumbnail edit mode")

    await state.set_state(VerificationStates.editing_thumbnail)
    await callback.answer("🖼️ Send a timestamp or upload a cover photo")

    duration = format_duration(job.metadata.duration)

    if callback.message:
        await callback.message.reply(
            f"🖼️ **Set Thumbnail Timestamp**\n\n"
            f"Video duration: {duration}\n\n"
            f"Send one of:\n"
            f"• A timestamp: `00:04`, `0:30`, `1:15`\n"
            f"• Milliseconds: `4500`\n"
            f"• Seconds: `4`, `30`, `75`\n\n"
            f"_Or upload a custom cover photo (1080x1920 recommended)._",
            parse_mode="Markdown",
            reply_markup=build_cancel_keyboard(job.job_id),
        )


@router.message(VerificationStates.editing_thumbnail)
async def receive_thumbnail_input(message: Message, state: FSMContext) -> None:
    """Receive a timestamp or uploaded photo for the thumbnail."""
    job = await _get_job(state)
    if not job:
        await message.reply("⚠️ No active job. Send a new Reel URL to start.")
        await state.clear()
        return

    log = get_job_logger(job.job_id)

    # Handle uploaded photo
    if message.photo:
        # Use the largest photo
        photo = message.photo[-1]
        photo_path = Path(job.work_dir) / "custom_thumb.jpg" if job.work_dir else None

        if photo_path:
            file = await message.bot.get_file(photo.file_id)
            await message.bot.download_file(file.file_path, str(photo_path))
            job.thumbnail_path = photo_path
            await _save_job(state, job)
            log.info("Custom thumbnail uploaded")

            await message.reply(
                "✅ Custom thumbnail set! Returning to review...",
                reply_markup=build_verification_keyboard(job.job_id),
            )
            await state.set_state(VerificationStates.waiting_approval)
            return

    # Handle timestamp text
    if not message.text:
        await message.reply("⚠️ Send a timestamp (e.g., `00:04`) or upload a photo.")
        return

    try:
        thumb_ms = parse_to_ms(message.text)
    except ValueError as exc:
        await message.reply(f"⚠️ {exc}\n\nTry formats like `00:04`, `4500`, or `30`.")
        return

    job.thumb_offset_ms = thumb_ms
    log.info("Thumbnail timestamp set", offset_ms=thumb_ms)

    # Extract new thumbnail at the specified timestamp
    if job.processed_video_path and job.work_dir:
        try:
            new_thumb = await video_editor.extract_thumbnail_at_timestamp(
                video_path=Path(job.processed_video_path),
                output_dir=Path(job.work_dir),
                job_id=job.job_id,
                timestamp_ms=thumb_ms,
            )
            job.thumbnail_path = new_thumb

            # Send the new thumbnail preview
            thumb_file = FSInputFile(str(new_thumb))
            await message.reply_photo(
                photo=thumb_file,
                caption=(
                    f"🖼️ **Thumbnail Updated**\n\n"
                    f"Timestamp: `{message.text}` ({thumb_ms}ms)\n\n"
                    f"Returning to review..."
                ),
                parse_mode="Markdown",
                reply_markup=build_verification_keyboard(job.job_id),
            )

        except Exception as exc:
            log.error("Thumbnail extraction failed", error=str(exc))
            await message.reply(
                f"⚠️ Thumbnail extraction failed: `{str(exc)[:100]}`\n"
                f"The IG API will use the offset at `{thumb_ms}ms` instead.",
                parse_mode="Markdown",
                reply_markup=build_verification_keyboard(job.job_id),
            )
    else:
        await message.reply(
            f"✅ Thumbnail offset set to `{thumb_ms}ms`.\n\n"
            f"Returning to review...",
            parse_mode="Markdown",
            reply_markup=build_verification_keyboard(job.job_id),
        )

    await _save_job(state, job)
    await state.set_state(VerificationStates.waiting_approval)


# ── Discard ───────────────────────────────────────

@router.callback_query(F.data.startswith("discard:"))
async def on_discard(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle the Discard button — cancel the job and clean up files."""
    job = await _get_job(state)
    if not job:
        await callback.answer("⚠️ Job not found.", show_alert=True)
        return

    log = get_job_logger(job.job_id)
    log.info("Admin discarded job")

    job.status = JobStatus.DISCARDED

    # Clean up temp directory
    cleanup_job_dir(job.job_id)

    if callback.message:
        await callback.message.edit_caption(
            caption=(
                f"🗑️ **Job Discarded**\n\n"
                f"Job `{job.job_id}` has been cancelled and all files purged.\n"
                f"Send a new Reel URL to start another job."
            ),
            parse_mode="Markdown",
            reply_markup=None,
        )

    await state.clear()


# ── Cancel Edit ───────────────────────────────────

@router.callback_query(F.data.startswith("cancel_edit:"))
async def on_cancel_edit(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle the Cancel Edit button — return to approval state."""
    job = await _get_job(state)
    if not job:
        await callback.answer("⚠️ Job not found.", show_alert=True)
        return

    log = get_job_logger(job.job_id)
    log.info("Admin cancelled edit — returning to approval")

    await state.set_state(VerificationStates.waiting_approval)
    await callback.answer("↩️ Returned to review mode")

    if callback.message:
        await callback.message.edit_text(
            "↩️ Edit cancelled. Use the buttons on the video preview above.",
        )


# ── No-op Handler (for disabled buttons) ─────────

@router.callback_query(F.data == "noop")
async def on_noop(callback: CallbackQuery) -> None:
    """Handle no-op callback data (e.g., from disabled/loading buttons)."""
    await callback.answer("⏳ Please wait — operation in progress...")
