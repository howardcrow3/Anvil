"""Gateway server that bridges platform adapters to the agent loop."""

from __future__ import annotations

import asyncio
import logging
import signal
import os
from typing import Any, Awaitable, Callable

from anvil_agent.agent_loop import AgentLoop, SYSTEM_PROMPT
from anvil_agent.gateway.config import (
    GatewayConfig,
    load_gateway_config,
    save_gateway_config,
)
from anvil_agent.gateway.session_router import SessionRouter
from anvil_agent.models.types import ChatMessage
from anvil_agent.session.manager import SessionManager
from anvil_agent.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class GatewayServer:
    """Core gateway server that manages platform adapters and routes messages."""

    def __init__(
        self,
        config: GatewayConfig,
        agent_loop_factory: Callable[[], AgentLoop],
        session_manager: SessionManager,
        tool_registry: ToolRegistry,
    ) -> None:
        self._config = config
        self._agent_loop_factory = agent_loop_factory
        self._session_manager = session_manager
        self._tool_registry = tool_registry
        self._session_router = SessionRouter(session_manager)
        self._adapters: dict[str, Any] = {}
        self._message_queues: dict[str, asyncio.Queue[tuple[str, str, str, asyncio.Future[str]]]] = {}
        self._workers: dict[str, asyncio.Task[None]] = {}
        self._running = False

    async def start(self) -> None:
        """Start all enabled platform adapters."""
        self._running = True

        if self._config.telegram and self._config.telegram.enabled:
            try:
                from anvil_agent.gateway.adapters.telegram import TelegramAdapter

                adapter = TelegramAdapter(
                    self._config.telegram, on_message=self.handle_message
                )
                self._adapters["telegram"] = adapter
                await adapter.start()
                logger.info("Telegram adapter started")
            except ImportError:
                logger.warning(
                    "python-telegram-bot not installed, skipping Telegram adapter"
                )

        if self._config.discord and self._config.discord.enabled:
            try:
                from anvil_agent.gateway.adapters.discord import DiscordAdapter

                adapter = DiscordAdapter(
                    self._config.discord, on_message=self.handle_message
                )
                self._adapters["discord"] = adapter
                await adapter.start()
                logger.info("Discord adapter started")
            except ImportError:
                logger.warning(
                    "discord.py not installed, skipping Discord adapter"
                )

        if self._config.slack and self._config.slack.enabled:
            try:
                from anvil_agent.gateway.adapters.slack import SlackAdapter

                adapter = SlackAdapter(
                    self._config.slack, on_message=self.handle_message
                )
                self._adapters["slack"] = adapter
                await adapter.start()
                logger.info("Slack adapter started")
            except ImportError:
                logger.warning(
                    "slack-bolt not installed, skipping Slack adapter"
                )

        if self._config.webhook and self._config.webhook.enabled:
            try:
                from anvil_agent.gateway.adapters.webhook import WebhookAdapter

                adapter = WebhookAdapter(
                    self._config.webhook, on_message=self.handle_message
                )
                self._adapters["webhook"] = adapter
                await adapter.start()
                logger.info("Webhook adapter started")
            except ImportError:
                logger.warning(
                    "aiohttp not installed, skipping Webhook adapter"
                )

        logger.info(
            "Gateway started with %d adapter(s): %s",
            len(self._adapters),
            list(self._adapters.keys()),
        )

    async def stop(self) -> None:
        """Stop all adapters gracefully."""
        self._running = False

        for name, worker in self._workers.items():
            worker.cancel()
        self._workers.clear()

        for name, adapter in self._adapters.items():
            try:
                await adapter.stop()
                logger.info("Stopped %s adapter", name)
            except Exception as exc:
                logger.error("Error stopping %s adapter: %s", name, exc)

        self._adapters.clear()
        logger.info("Gateway stopped")

    async def handle_message(
        self, platform: str, user_id: str, text: str
    ) -> str:
        """Core message handler: route incoming message through the agent.

        1. Check allowlist for platform
        2. Get/create session via SessionRouter
        3. Create AgentLoop if needed
        4. Run message through agent loop, collect full response
        5. Save messages to session
        6. Return response text
        """
        # Check allowlist
        if not self._check_allowed(platform, user_id):
            return "You are not authorized to use this bot."

        # Get or create session
        session_id, messages = self._session_router.get_or_create_session(
            platform, user_id
        )

        # Handle special commands
        if text.strip().lower() in ("/new", "/reset"):
            self._session_router.reset_session(platform, user_id)
            return "Session reset. Starting fresh."

        # Enqueue message and wait for response
        queue_key = f"{platform}:{user_id}"
        if queue_key not in self._message_queues:
            self._message_queues[queue_key] = asyncio.Queue()
            self._workers[queue_key] = asyncio.create_task(
                self._worker(queue_key)
            )

        future: asyncio.Future[str] = asyncio.get_event_loop().create_future()
        await self._message_queues[queue_key].put((platform, user_id, text, future))
        return await future

    async def _worker(self, queue_key: str) -> None:
        """Process messages sequentially per user."""
        queue = self._message_queues[queue_key]
        while self._running:
            try:
                platform, user_id, text, future = await asyncio.wait_for(
                    queue.get(), timeout=300.0
                )
            except asyncio.TimeoutError:
                # Clean up idle workers
                break
            except asyncio.CancelledError:
                break

            try:
                response = await self._process_message(platform, user_id, text)
                if not future.done():
                    future.set_result(response)
            except Exception as exc:
                logger.exception("Error processing message for %s", queue_key)
                if not future.done():
                    future.set_result(f"Error: {exc}")

        # Clean up
        self._message_queues.pop(queue_key, None)
        self._workers.pop(queue_key, None)

    async def _process_message(
        self, platform: str, user_id: str, text: str
    ) -> str:
        """Process a single message through the agent loop."""
        session_id, messages = self._session_router.get_or_create_session(
            platform, user_id
        )

        # Add user message
        user_msg = ChatMessage(role="user", content=text)
        messages.append(user_msg)
        self._session_router.save_message(platform, user_id, user_msg)

        # Auto-name session on first message
        if len(messages) == 1:
            self._session_manager.auto_name(session_id, text)

        # Create agent loop and run
        agent_loop = self._agent_loop_factory()
        full_response = ""

        async for event in agent_loop.run(messages):
            if event.get("type") == "text_delta":
                full_response += event.get("text", "")

        # Save assistant response
        if full_response:
            assistant_msg = ChatMessage(role="assistant", content=full_response)
            self._session_router.save_message(platform, user_id, assistant_msg)

        return full_response or "No response generated."

    def _check_allowed(self, platform: str, user_id: str) -> bool:
        """Check if a user is in the allowlist for the given platform."""
        config = getattr(self._config, platform, None)
        if config is None:
            return False

        allowed = getattr(config, "allowed_users", [])
        if not allowed:
            return True  # Empty allowlist means allow all

        # Telegram uses int IDs, others use strings
        if platform == "telegram":
            try:
                return int(user_id) in allowed
            except (ValueError, TypeError):
                return False
        return user_id in allowed

    def get_status(self) -> dict[str, Any]:
        """Return status of all adapters."""
        status: dict[str, Any] = {
            "running": self._running,
            "adapters": {},
        }
        for name, adapter in self._adapters.items():
            status["adapters"][name] = {
                "running": adapter.is_running,
                "name": adapter.name,
            }
        return status


def main() -> None:
    """Standalone entry point for anvil-gateway."""
    import argparse

    from rich.logging import RichHandler

    from anvil_agent.models.claude_provider import ClaudeProvider
    from anvil_agent.models.router import ModelRouter
    from anvil_agent.settings import SettingsManager
    from anvil_agent.tools import create_default_registry

    parser = argparse.ArgumentParser(description="Anvil Messaging Gateway")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(message)s",
        handlers=[RichHandler(rich_tracebacks=True)],
    )

    async def async_main() -> None:
        settings = SettingsManager()
        config = load_gateway_config()

        # Set up model router
        router = ModelRouter()
        api_key = settings.get_api_key()
        default_model = settings.get("default_model") or "claude-sonnet-4-20250514"

        if api_key:
            provider = ClaudeProvider(model=default_model, api_key=api_key)
            router.register(default_model, provider, provider_type="cloud")

        tool_registry = create_default_registry()
        session_manager = SessionManager()

        def agent_loop_factory() -> AgentLoop:
            return AgentLoop(
                provider=router.active,
                tool_registry=tool_registry,
                system_prompt=SYSTEM_PROMPT,
            )

        gateway = GatewayServer(
            config=config,
            agent_loop_factory=agent_loop_factory,
            session_manager=session_manager,
            tool_registry=tool_registry,
        )

        loop = asyncio.get_running_loop()
        shutdown_event = asyncio.Event()

        def signal_handler() -> None:
            shutdown_event.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, signal_handler)

        await gateway.start()
        logger.info("Gateway running. Press Ctrl+C to stop.")
        await shutdown_event.wait()
        await gateway.stop()

    asyncio.run(async_main())


if __name__ == "__main__":
    main()
