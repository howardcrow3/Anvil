"""Telegram platform adapter using python-telegram-bot."""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

try:
    from telegram import Update
    from telegram.ext import (
        Application,
        CommandHandler,
        ContextTypes,
        MessageHandler,
        filters,
    )

    HAS_TELEGRAM = True
except ImportError:
    HAS_TELEGRAM = False

from anvil_agent.gateway.adapters.base import PlatformAdapter
from anvil_agent.gateway.config import TelegramConfig

logger = logging.getLogger(__name__)

MAX_MESSAGE_LENGTH = 4096


class TelegramAdapter(PlatformAdapter):
    """Telegram bot adapter."""

    def __init__(
        self,
        config: TelegramConfig,
        on_message: Callable[[str, str, str], Awaitable[str]] | None = None,
    ) -> None:
        super().__init__()
        if not HAS_TELEGRAM:
            raise ImportError("python-telegram-bot is required for Telegram adapter")
        self._config = config
        self.on_message = on_message
        self._app: Application | None = None  # type: ignore[type-arg]
        self._task: asyncio.Task[None] | None = None

    @property
    def name(self) -> str:
        return "telegram"

    async def start(self) -> None:
        """Start the Telegram bot with polling."""
        builder = Application.builder().token(self._config.bot_token)
        self._app = builder.build()

        # Register handlers
        self._app.add_handler(CommandHandler("new", self._cmd_new))
        self._app.add_handler(CommandHandler("model", self._cmd_model))
        self._app.add_handler(CommandHandler("skills", self._cmd_skills))
        self._app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message)
        )

        await self._app.initialize()
        await self._app.start()
        self._task = asyncio.create_task(self._run_polling())
        self._running = True
        logger.info("Telegram adapter started")

    async def _run_polling(self) -> None:
        """Run polling in background."""
        if self._app is None:
            return
        try:
            await self._app.updater.start_polling(drop_pending_updates=True)  # type: ignore[union-attr]
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("Telegram polling error: %s", exc)

    async def stop(self) -> None:
        """Stop the Telegram bot."""
        self._running = False
        if self._app:
            if self._app.updater and self._app.updater.running:
                await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
        if self._task:
            self._task.cancel()
            self._task = None
        logger.info("Telegram adapter stopped")

    async def send_response(self, user_id: str, text: str) -> None:
        """Send a message to a Telegram user."""
        if not self._app or not self._app.bot:
            return
        for chunk in _split_message(text):
            try:
                await self._app.bot.send_message(
                    chat_id=int(user_id),
                    text=chunk,
                    parse_mode="Markdown",
                )
            except Exception:
                # Fallback without Markdown if parsing fails
                await self._app.bot.send_message(
                    chat_id=int(user_id),
                    text=chunk,
                )

    def _is_allowed(self, user_id: int) -> bool:
        """Check if user is in the allowlist."""
        if not self._config.allowed_users:
            return True
        return user_id in self._config.allowed_users

    async def _handle_message(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE  # type: ignore[type-arg]
    ) -> None:
        """Handle incoming text messages."""
        if not update.message or not update.message.text:
            return
        if not update.effective_user:
            return

        user_id = update.effective_user.id
        if not self._is_allowed(user_id):
            await update.message.reply_text("You are not authorized to use this bot.")
            return

        if self.on_message is None:
            await update.message.reply_text("Bot is not connected to agent.")
            return

        # Show typing indicator
        await update.message.chat.send_action("typing")

        response = await self.on_message("telegram", str(user_id), update.message.text)
        for chunk in _split_message(response):
            try:
                await update.message.reply_text(chunk, parse_mode="Markdown")
            except Exception:
                await update.message.reply_text(chunk)

    async def _cmd_new(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE  # type: ignore[type-arg]
    ) -> None:
        """Handle /new command - reset session."""
        if not update.message or not update.effective_user:
            return
        if not self._is_allowed(update.effective_user.id):
            return
        if self.on_message:
            await self.on_message("telegram", str(update.effective_user.id), "/new")
        await update.message.reply_text("Session reset. Starting fresh.")

    async def _cmd_model(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE  # type: ignore[type-arg]
    ) -> None:
        """Handle /model command - show current model."""
        if not update.message:
            return
        await update.message.reply_text("Current model info not available via gateway.")

    async def _cmd_skills(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE  # type: ignore[type-arg]
    ) -> None:
        """Handle /skills command - list skills."""
        if not update.message:
            return
        await update.message.reply_text("Skills listing not available via gateway.")


def _split_message(text: str) -> list[str]:
    """Split a message into chunks that fit within Telegram's limit."""
    if len(text) <= MAX_MESSAGE_LENGTH:
        return [text]

    chunks: list[str] = []
    while text:
        if len(text) <= MAX_MESSAGE_LENGTH:
            chunks.append(text)
            break
        # Try to split at a newline
        split_at = text.rfind("\n", 0, MAX_MESSAGE_LENGTH)
        if split_at == -1:
            split_at = MAX_MESSAGE_LENGTH
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks
