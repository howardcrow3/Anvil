"""Slack platform adapter using slack-bolt."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

try:
    from slack_bolt.async_app import AsyncApp
    from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

    HAS_SLACK = True
except ImportError:
    HAS_SLACK = False

from anvil_agent.gateway.adapters.base import PlatformAdapter
from anvil_agent.gateway.config import SlackConfig

logger = logging.getLogger(__name__)


class SlackAdapter(PlatformAdapter):
    """Slack bot adapter using Socket Mode."""

    def __init__(
        self,
        config: SlackConfig,
        on_message: Callable[[str, str, str], Awaitable[str]] | None = None,
    ) -> None:
        super().__init__()
        if not HAS_SLACK:
            raise ImportError("slack-bolt is required for Slack adapter")
        self._config = config
        self.on_message = on_message
        self._app: AsyncApp | None = None
        self._handler: AsyncSocketModeHandler | None = None
        self._task: asyncio.Task[None] | None = None

    @property
    def name(self) -> str:
        return "slack"

    async def start(self) -> None:
        """Start the Slack bot in Socket Mode."""
        self._app = AsyncApp(token=self._config.bot_token)

        @self._app.event("message")
        async def handle_message(event: dict[str, Any], say: Any) -> None:
            await self._handle_message(event, say)

        self._handler = AsyncSocketModeHandler(
            self._app, self._config.app_token
        )
        self._task = asyncio.create_task(self._run_handler())
        self._running = True
        logger.info("Slack adapter started (Socket Mode)")

    async def _run_handler(self) -> None:
        """Run the socket mode handler."""
        if self._handler is None:
            return
        try:
            await self._handler.start_async()
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("Slack handler error: %s", exc)

    async def stop(self) -> None:
        """Stop the Slack bot."""
        self._running = False
        if self._handler:
            await self._handler.close_async()
        if self._task:
            self._task.cancel()
            self._task = None
        logger.info("Slack adapter stopped")

    async def send_response(self, user_id: str, text: str) -> None:
        """Send a DM to a Slack user."""
        if not self._app:
            return
        try:
            blocks = _format_blocks(text)
            await self._app.client.chat_postMessage(
                channel=user_id,
                text=text,
                blocks=blocks,
            )
        except Exception as exc:
            logger.error("Failed to send Slack message to %s: %s", user_id, exc)

    def _is_allowed(self, user_id: str) -> bool:
        """Check if user is in the allowlist."""
        if not self._config.allowed_users:
            return True
        return user_id in self._config.allowed_users

    async def _handle_message(self, event: dict[str, Any], say: Any) -> None:
        """Handle incoming Slack message events."""
        # Ignore bot messages
        if event.get("bot_id"):
            return

        user_id = event.get("user", "")
        text = event.get("text", "")
        thread_ts = event.get("thread_ts") or event.get("ts")

        if not user_id or not text:
            return

        if not self._is_allowed(user_id):
            await say(
                text="You are not authorized to use this bot.",
                thread_ts=thread_ts,
            )
            return

        if self.on_message is None:
            await say(
                text="Bot is not connected to agent.",
                thread_ts=thread_ts,
            )
            return

        response = await self.on_message("slack", user_id, text)
        blocks = _format_blocks(response)
        await say(text=response, blocks=blocks, thread_ts=thread_ts)


def _format_blocks(text: str) -> list[dict[str, Any]]:
    """Format response as Slack blocks."""
    blocks: list[dict[str, Any]] = []

    # Split into code and non-code sections
    parts = text.split("```")
    for i, part in enumerate(parts):
        if not part.strip():
            continue
        if i % 2 == 0:
            # Regular text
            # Slack section blocks have a 3000 char limit
            while part:
                chunk = part[:3000]
                part = part[3000:]
                blocks.append({
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": chunk},
                })
        else:
            # Code block
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"```{part}```"},
            })

    return blocks if blocks else [
        {"type": "section", "text": {"type": "mrkdwn", "text": text or "(empty response)"}}
    ]
