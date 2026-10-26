"""
ReelForge Inline Keyboard Builders.

Constructs the interactive inline keyboard markup for the Reel
verification workflow in Telegram.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.config import settings


def build_verification_keyboard(job_id: str, ig_enabled: bool | None = None) -> InlineKeyboardMarkup:
    """
    Build the main verification inline keyboard for a processed Reel.

    Provides buttons for: Approve (Publish or Save), Edit Caption,
    Regenerate Caption, Set Thumbnail Timestamp, and Discard.

    Args:
        job_id: Unique job identifier embedded in callback data.
        ig_enabled: Whether Instagram publishing is available (defaults to config setting).

    Returns:
        InlineKeyboardMarkup ready to attach to a Telegram message.
    """
    use_ig = settings.ig_enabled if ig_enabled is None else ig_enabled
    approve_text = "✅ Approve & Publish to IG" if use_ig else "✅ Approve & Save Reel"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=approve_text,
                    callback_data=f"approve:{job_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Edit Caption",
                    callback_data=f"edit_caption:{job_id}",
                ),
                InlineKeyboardButton(
                    text="🔄 Regenerate Caption",
                    callback_data=f"regenerate:{job_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🖼️ Set Thumbnail Timestamp",
                    callback_data=f"set_thumb:{job_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="❌ Discard",
                    callback_data=f"discard:{job_id}",
                ),
            ],
        ]
    )


def build_cancel_keyboard(job_id: str) -> InlineKeyboardMarkup:
    """
    Build a simple cancel keyboard for FSM states (caption/thumbnail editing).

    Args:
        job_id: Unique job identifier embedded in callback data.

    Returns:
        InlineKeyboardMarkup with a single Cancel button.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="↩️ Cancel & Go Back",
                    callback_data=f"cancel_edit:{job_id}",
                ),
            ],
        ]
    )


def build_publishing_keyboard() -> InlineKeyboardMarkup:
    """
    Build a disabled-looking keyboard shown during publishing.

    Returns:
        InlineKeyboardMarkup with a single "publishing in progress" indicator.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⏳ Publishing in progress...",
                    callback_data="noop",
                ),
            ],
        ]
    )
