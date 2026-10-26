"""
ReelForge Start & Utility Command Handlers.

Handles /start, /help, /status, and /token_health commands for
bot introduction, usage guidance, and operational health checks.
"""

from __future__ import annotations

from datetime import datetime, timezone

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.config import settings
from app.services.instagram_api import InstagramPublisher
from app.utils.logger import logger

router = Router(name="start")


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    """Handle the /start command with a welcome message and usage overview."""
    publish_step = (
        "6️⃣ Publish directly to your Instagram!\n\n"
        if settings.ig_enabled
        else "6️⃣ Deliver high-quality repurposed video & caption in Telegram!\n\n"
    )

    token_cmd = (
        "• `/token_health` — Check Instagram API token validity\n\n"
        if settings.ig_enabled
        else "• `/token_health` — Instagram API status (currently disabled)\n\n"
    )

    welcome_text = (
        "🎬 **ReelForge Bot** — Instagram Reels Repurposing Engine\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Send me a public Instagram Reel or Post URL and I'll:\n\n"
        "1️⃣ Download the video in highest quality\n"
        "2️⃣ Transcribe speech → burn subtitles\n"
        "3️⃣ Apply originality transforms (watermark, speed shift, audio EQ)\n"
        "4️⃣ Generate a high-converting caption via AI\n"
        "5️⃣ Present it for your interactive approval\n"
        f"{publish_step}"
        "**Commands:**\n"
        "• `/help` — Show instructions\n"
        "• `/status` — Bot operational status\n"
        f"{token_cmd}"
        "**Usage:** Just paste an Instagram URL to get started! 🚀"
    )

    await message.reply(welcome_text, parse_mode="Markdown")
    logger.info("Start command", user_id=message.from_user.id if message.from_user else 0)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    """Handle the /help command with detailed usage instructions."""
    approve_desc = (
        "   • ✅ **Approve & Publish** — Upload directly to Instagram\n"
        if settings.ig_enabled
        else "   • ✅ **Approve & Save** — Deliver the final video & copy-paste caption\n"
    )

    help_text = (
        "📖 **ReelForge Bot — Help Guide**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "**How to use:**\n"
        "1. Send a public Instagram Reel/Post URL\n"
        "   Example: `https://www.instagram.com/reel/ABC123/`\n\n"
        "2. Wait for processing (download → transcribe → transform → caption)\n\n"
        "3. Review the preview and caption, then use the buttons:\n"
        f"{approve_desc}"
        "   • ✏️ **Edit Caption** — Replace with your own custom text\n"
        "   • 🔄 **Regenerate Caption** — Get a fresh AI caption\n"
        "   • 🖼️ **Set Thumbnail** — Pick a cover frame timestamp\n"
        "   • ❌ **Discard** — Cancel and delete all files\n\n"
        "**Supported URL formats:**\n"
        "• `instagram.com/reel/...`\n"
        "• `instagram.com/p/...`\n"
        "• `instagram.com/reels/...`\n\n"
        f"**Current watermark:** `{settings.watermark_text}`\n"
        f"**LLM provider:** `{settings.llm_provider}` / `{settings.llm_model_name}`\n"
        f"**Instagram upload:** `{'🟢 Enabled' if settings.ig_enabled else '⚪ Disabled'}`"
    )

    await message.reply(help_text, parse_mode="Markdown")


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    """Handle the /status command with bot operational information."""
    now = datetime.now(timezone.utc)

    ig_status = "🟢 Enabled" if settings.ig_enabled else "⚪ Disabled (Repurpose & Download mode)"

    status_text = (
        "📊 **Bot Status**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🟢 **Status:** Online\n"
        f"⏰ **Server Time:** {now.strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
        f"🎯 **Watermark:** `{settings.watermark_text}`\n"
        f"🧠 **Whisper Model:** `{settings.whisper_model_size}`\n"
        f"🤖 **LLM:** `{settings.llm_provider}` / `{settings.llm_model_name}`\n"
        f"📡 **Instagram Upload:** {ig_status}\n"
    )

    await message.reply(status_text, parse_mode="Markdown")


@router.message(Command("token_health"))
async def cmd_token_health(message: Message) -> None:
    """Handle the /token_health command to check Instagram API token validity."""
    if not settings.ig_enabled:
        text = (
            "ℹ️ **Instagram API Disabled**\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "No Meta Graph API credentials are configured in `.env` (`IG_USER_ID` / `IG_ACCESS_TOKEN`).\n\n"
            "The bot is running in **Local Repurposing Mode**:\n"
            "• Downloads reels in high resolution\n"
            "• Transcribes speech & burns styled subtitles\n"
            "• Applies originality transforms (watermark, speed shift, audio EQ)\n"
            "• Generates viral AI captions & hashtags\n"
            "• Delivers ready-to-post video files directly in Telegram\n\n"
            "_You can enable Instagram direct publishing anytime by configuring your Meta API credentials in `.env`._"
        )
        await message.reply(text, parse_mode="Markdown")
        return

    await message.reply("🔍 Checking Instagram API token health...", parse_mode="Markdown")

    try:
        publisher = InstagramPublisher()
        health = await publisher.check_token_health()

        if health["is_valid"]:
            expires_at = health["expires_at"]
            if expires_at:
                expires_dt = datetime.fromtimestamp(expires_at, tz=timezone.utc)
                remaining = expires_dt - datetime.now(timezone.utc)
                days_left = remaining.days
                expiry_str = f"{expires_dt.strftime('%Y-%m-%d %H:%M')} UTC ({days_left} days left)"
            else:
                expiry_str = "Never (long-lived token)"

            scopes = ", ".join(health.get("scopes", []))

            text = (
                "✅ **Token Status: Valid**\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📅 **Expires:** {expiry_str}\n"
                f"🔑 **Scopes:** `{scopes}`\n"
                f"📱 **App ID:** `{health.get('app_id', 'N/A')}`\n"
            )

            if days_left < 7:
                text += "\n⚠️ **Warning:** Token expires soon! Refresh it before it expires."
        else:
            error = health.get("error", {})
            text = (
                "❌ **Token Status: Invalid**\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"**Error:** {error.get('message', 'Unknown error')}\n"
                f"**Code:** {error.get('code', 'N/A')}\n\n"
                "See `docs/META_API_SETUP.md` for token refresh instructions."
            )

        await message.reply(text, parse_mode="Markdown")

    except Exception as exc:
        await message.reply(
            f"❌ **Token check failed:**\n`{exc}`",
            parse_mode="Markdown",
        )
