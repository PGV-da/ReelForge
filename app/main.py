"""
ReelForge Application Entrypoint.

Initializes the Telegram Bot, Dispatcher, FSM storage, registers all
routers and middleware, and starts long-polling.
"""

from __future__ import annotations

import asyncio
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage

from app.config import settings
from app.utils.logger import logger


async def main() -> None:
    """Initialize and start the ReelForge Telegram Bot."""
    logger.info("=" * 50)
    logger.info("ReelForge Starting")
    logger.info("=" * 50)

    # ── Initialize FSM Storage ────────────────────
    storage: MemoryStorage

    if settings.redis_url:
        try:
            from aiogram.fsm.storage.redis import RedisStorage
            from redis.asyncio import Redis

            redis_client = Redis.from_url(settings.redis_url)
            storage = RedisStorage(redis=redis_client)
            logger.info("FSM Storage: Redis", url=settings.redis_url)
        except ImportError:
            logger.warning("Redis package not installed — falling back to MemoryStorage")
            storage = MemoryStorage()
    else:
        storage = MemoryStorage()
        logger.info("FSM Storage: Memory (data lost on restart)")

    # ── Initialize Bot & Dispatcher ───────────────
    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode="Markdown"),
    )

    dp = Dispatcher(storage=storage)

    # ── Register Middleware ───────────────────────
    from app.bot.middlewares import AdminOnlyMiddleware

    dp.message.middleware(AdminOnlyMiddleware())
    dp.callback_query.middleware(AdminOnlyMiddleware())
    logger.info("Middleware registered: AdminOnly access control")

    # ── Register Routers ──────────────────────────
    from app.bot.handlers import ingest, start, verification

    # Order matters: start commands first, then verification callbacks,
    # then ingest (which catches all other messages)
    dp.include_router(start.router)
    dp.include_router(verification.router)
    dp.include_router(ingest.router)
    logger.info("Routers registered: start, verification, ingest")

    # ── Ensure Temp Directory Exists ──────────────
    settings.temp_base_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Temp directory ready", path=str(settings.temp_base_dir))

    # ── Log Configuration Summary ─────────────────
    logger.info("Configuration Summary:")
    logger.info(f"  Admin IDs: {settings.admin_user_ids}")
    logger.info(f"  Watermark: {settings.watermark_text}")
    logger.info(f"  Whisper Model: {settings.whisper_model_size}")
    logger.info(f"  LLM: {settings.llm_provider} / {settings.llm_model_name}")
    logger.info(f"  Instagram Auto-Publish: {'Enabled (' + str(settings.ig_user_id) + ')' if settings.ig_enabled else 'Disabled (Local Repurpose Mode)'}")

    # ── Start Polling ─────────────────────────────
    logger.info("Bot is now polling for updates... 🚀")

    try:
        # Delete webhook to ensure clean polling start
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot, allowed_updates=["message", "callback_query"])
    except Exception as exc:
        logger.critical("Bot crashed", error=str(exc), exc_info=True)
        raise
    finally:
        await bot.session.close()
        logger.info("Bot session closed. Goodbye!")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user (Ctrl+C)")
        sys.exit(0)
