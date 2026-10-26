"""
ReelForge Access Control Middleware.

Implements an aiogram middleware that rejects messages and callback queries
from any Telegram user not in the ADMIN_USER_IDS whitelist. Unauthorized
users receive a polite denial message; all unauthorized access attempts
are logged.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.config import settings
from app.utils.logger import logger


class AdminOnlyMiddleware(BaseMiddleware):
    """
    Middleware that restricts bot access to whitelisted admin user IDs.

    Attached to the Dispatcher, this middleware intercepts all incoming
    updates and blocks processing for unauthorized users.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        """
        Intercept incoming events and verify the user is an authorized admin.

        Args:
            handler: The next handler in the middleware chain.
            event: The incoming Telegram event (Message or CallbackQuery).
            data: Handler data dictionary.

        Returns:
            Result of the next handler if authorized, None otherwise.
        """
        user_id: int | None = None

        if isinstance(event, Message) and event.from_user:
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery) and event.from_user:
            user_id = event.from_user.id

        # Allow system events without a user (e.g., channel posts)
        if user_id is None:
            return await handler(event, data)

        if user_id not in settings.admin_user_ids:
            logger.warning(
                "Unauthorized access attempt",
                user_id=user_id,
                username=getattr(event, "from_user", None)
                and getattr(event.from_user, "username", "unknown"),
            )

            # Send denial message
            if isinstance(event, Message):
                await event.reply(
                    "⛔ **Access Denied**\n\n"
                    "This bot is restricted to authorized administrators.\n"
                    "Contact the bot owner if you believe this is an error.",
                    parse_mode="Markdown",
                )
            elif isinstance(event, CallbackQuery):
                await event.answer(
                    "⛔ Access denied — admin only.",
                    show_alert=True,
                )

            return None  # Block the handler

        return await handler(event, data)
