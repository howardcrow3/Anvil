"""Webhook platform adapter using aiohttp."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any, Awaitable, Callable

try:
    from aiohttp import web

    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False

from anvil_agent.gateway.adapters.base import PlatformAdapter
from anvil_agent.gateway.config import WebhookConfig

logger = logging.getLogger(__name__)


class WebhookAdapter(PlatformAdapter):
    """Webhook server adapter using aiohttp."""

    def __init__(
        self,
        config: WebhookConfig,
        on_message: Callable[[str, str, str], Awaitable[str]] | None = None,
    ) -> None:
        super().__init__()
        if not HAS_AIOHTTP:
            raise ImportError("aiohttp is required for Webhook adapter")
        self._config = config
        self.on_message = on_message
        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None

    @property
    def name(self) -> str:
        return "webhook"

    async def start(self) -> None:
        """Start the webhook HTTP server."""
        self._app = web.Application()
        self._app.router.add_post("/webhook/chat", self._handle_chat)
        self._app.router.add_get("/webhook/health", self._handle_health)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, "0.0.0.0", self._config.port)
        await self._site.start()
        self._running = True
        logger.info("Webhook adapter started on port %d", self._config.port)

    async def stop(self) -> None:
        """Stop the webhook server."""
        self._running = False
        if self._site:
            await self._site.stop()
        if self._runner:
            await self._runner.cleanup()
        logger.info("Webhook adapter stopped")

    async def send_response(self, user_id: str, text: str) -> None:
        """Webhook responses are sent inline, not via this method."""
        pass

    def _verify_signature(self, body: bytes, signature: str) -> bool:
        """Verify HMAC-SHA256 signature."""
        if not self._config.hmac_secret:
            return True  # No secret configured, skip verification

        expected = hmac.new(
            self._config.hmac_secret.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(expected, signature)

    async def _handle_chat(self, request: web.Request) -> web.Response:
        """Handle POST /webhook/chat.

        Body: {"message": "...", "user_id": "...", "callback_url": "..."}
        """
        # Verify signature if secret is configured
        if self._config.hmac_secret:
            signature = request.headers.get("X-Signature", "")
            body = await request.read()
            if not self._verify_signature(body, signature):
                return web.json_response(
                    {"error": "Invalid signature"}, status=401
                )
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                return web.json_response(
                    {"error": "Invalid JSON"}, status=400
                )
        else:
            try:
                data = await request.json()
            except json.JSONDecodeError:
                return web.json_response(
                    {"error": "Invalid JSON"}, status=400
                )

        message = data.get("message", "")
        user_id = data.get("user_id", "anonymous")
        callback_url = data.get("callback_url")

        if not message:
            return web.json_response(
                {"error": "No message provided"}, status=400
            )

        if self.on_message is None:
            return web.json_response(
                {"error": "Bot is not connected to agent"}, status=503
            )

        response = await self.on_message("webhook", user_id, message)

        # If callback_url is provided, POST the response there
        if callback_url:
            try:
                import aiohttp

                async with aiohttp.ClientSession() as session:
                    await session.post(
                        callback_url,
                        json={"response": response, "user_id": user_id},
                    )
            except Exception as exc:
                logger.error("Failed to call callback URL %s: %s", callback_url, exc)

        return web.json_response({"response": response})

    async def _handle_health(self, request: web.Request) -> web.Response:
        """Handle GET /webhook/health."""
        return web.json_response({"status": "ok", "adapter": "webhook"})
