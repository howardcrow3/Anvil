"""Discord platform adapter using discord.py."""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

try:
    import discord
    from discord.ext import commands

    HAS_DISCORD = True
except ImportError:
    HAS_DISCORD = False

from anvil_agent.gateway.adapters.base import PlatformAdapter
from anvil_agent.gateway.config import DiscordConfig

logger = logging.getLogger(__name__)

MAX_MESSAGE_LENGTH = 2000


class DiscordAdapter(PlatformAdapter):
    """Discord bot adapter."""

    def __init__(
        self,
        config: DiscordConfig,
        on_message: Callable[[str, str, str], Awaitable[str]] | None = None,
    ) -> None:
        super().__init__()
        if not HAS_DISCORD:
            raise ImportError("discord.py is required for Discord adapter")
        self._config = config
        self.on_message = on_message
        self._client: discord.Client | None = None
        self._task: asyncio.Task[None] | None = None

    @property
    def name(self) -> str:
        return "discord"

    async def start(self) -> None:
        """Start the Discord bot."""
        intents = discord.Intents.default()
        intents.message_content = True
        self._client = discord.Client(intents=intents)

        @self._client.event
        async def on_ready() -> None:
            logger.info("Discord bot connected as %s", self._client.user)  # type: ignore[union-attr]

        @self._client.event
        async def on_message(message: discord.Message) -> None:
            await self._handle_message(message)

        self._task = asyncio.create_task(self._run_client())
        self._running = True
        logger.info("Discord adapter started")

    async def _run_client(self) -> None:
        """Run the Discord client in the background."""
        if self._client is None:
            return
        try:
            await self._client.start(self._config.bot_token)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("Discord client error: %s", exc)

    async def stop(self) -> None:
        """Stop the Discord bot."""
        self._running = False
        if self._client:
            await self._client.close()
        if self._task:
            self._task.cancel()
            self._task = None
        logger.info("Discord adapter stopped")

    async def send_response(self, user_id: str, text: str) -> None:
        """Send a DM to a Discord user."""
        if not self._client:
            return
        try:
            user = await self._client.fetch_user(int(user_id))
            for chunk in _split_message(text):
                await user.send(chunk)
        except Exception as exc:
            logger.error("Failed to send Discord DM to %s: %s", user_id, exc)

    def _is_allowed(self, user_id: str) -> bool:
        """Check if user is in the allowlist."""
        if not self._config.allowed_users:
            return True
        return user_id in self._config.allowed_users

    async def _handle_message(self, message: discord.Message) -> None:
        """Handle incoming Discord messages."""
        if not self._client:
            return
        # Ignore messages from the bot itself
        if message.author == self._client.user:
            return

        # Check if this is a DM or a mention in a channel
        is_dm = isinstance(message.channel, discord.DMChannel)
        is_mention = self._client.user in message.mentions if self._client.user else False

        if not is_dm and not is_mention:
            return

        user_id = str(message.author.id)
        if not self._is_allowed(user_id):
            await message.reply("You are not authorized to use this bot.")
            return

        if self.on_message is None:
            await message.reply("Bot is not connected to agent.")
            return

        # Strip the mention from the text if it's a channel mention
        text = message.content
        if is_mention and self._client.user:
            text = text.replace(f"<@{self._client.user.id}>", "").strip()

        # Use threads for channel conversations
        if not is_dm and hasattr(message.channel, "create_thread"):
            try:
                async with message.channel.typing():
                    response = await self.on_message("discord", user_id, text)
                thread = await message.create_thread(
                    name=text[:100] if text else "Anvil Chat"
                )
                for chunk in _split_message(response):
                    await thread.send(chunk)
                return
            except Exception as exc:
                logger.error("Failed to create thread: %s", exc)

        # DM or fallback: reply directly
        async with message.channel.typing():
            response = await self.on_message("discord", user_id, text)
        for chunk in _split_message(response):
            await message.reply(chunk)


def _split_message(text: str) -> list[str]:
    """Split a message into chunks that fit within Discord's limit."""
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
