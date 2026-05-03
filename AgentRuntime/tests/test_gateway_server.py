"""Tests for SessionRouter and GatewayServer."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from anvil_agent.gateway.config import (
    DiscordConfig,
    GatewayConfig,
    TelegramConfig,
    WebhookConfig,
)
from anvil_agent.gateway.server import GatewayServer
from anvil_agent.gateway.session_router import SessionRouter
from anvil_agent.models.types import ChatMessage
from anvil_agent.session.manager import SessionManager
from anvil_agent.tools.registry import ToolRegistry


# ---------------------------------------------------------------------------
# SessionRouter
# ---------------------------------------------------------------------------


class TestSessionRouter:
    def test_get_or_create_session_new(self, tmp_path):
        sm = SessionManager(sessions_dir=tmp_path)
        router = SessionRouter(sm)
        session_id, messages = router.get_or_create_session("telegram", "123")
        assert isinstance(session_id, str)
        assert messages == []

    def test_get_or_create_session_existing(self, tmp_path):
        sm = SessionManager(sessions_dir=tmp_path)
        router = SessionRouter(sm)
        sid1, _ = router.get_or_create_session("telegram", "123")
        sid2, _ = router.get_or_create_session("telegram", "123")
        assert sid1 == sid2

    def test_reset_session(self, tmp_path):
        sm = SessionManager(sessions_dir=tmp_path)
        router = SessionRouter(sm)
        sid1, _ = router.get_or_create_session("telegram", "123")
        router.reset_session("telegram", "123")
        sid2, _ = router.get_or_create_session("telegram", "123")
        assert sid1 != sid2

    def test_save_message(self, tmp_path):
        sm = SessionManager(sessions_dir=tmp_path)
        router = SessionRouter(sm)
        sid, _ = router.get_or_create_session("telegram", "123")
        msg = ChatMessage(role="user", content="hello")
        router.save_message("telegram", "123", msg)
        loaded = sm.load_messages(sid)
        assert len(loaded) == 1
        assert loaded[0].content == "hello"

    def test_different_platforms_different_sessions(self, tmp_path):
        sm = SessionManager(sessions_dir=tmp_path)
        router = SessionRouter(sm)
        sid_tg, _ = router.get_or_create_session("telegram", "123")
        sid_dc, _ = router.get_or_create_session("discord", "123")
        assert sid_tg != sid_dc


# ---------------------------------------------------------------------------
# GatewayServer allowlist
# ---------------------------------------------------------------------------


def _make_server(config: GatewayConfig, tmp_path) -> GatewayServer:
    sm = SessionManager(sessions_dir=tmp_path)
    return GatewayServer(
        config=config,
        agent_loop_factory=MagicMock(),
        session_manager=sm,
        tool_registry=ToolRegistry(),
    )


class TestGatewayServerAllowlist:
    def test_check_allowed_empty_allowlist(self, tmp_path):
        config = GatewayConfig(telegram=TelegramConfig(enabled=True))
        server = _make_server(config, tmp_path)
        assert server._check_allowed("telegram", "999") is True

    def test_check_allowed_telegram_int_id(self, tmp_path):
        config = GatewayConfig(
            telegram=TelegramConfig(enabled=True, allowed_users=[111, 222])
        )
        server = _make_server(config, tmp_path)
        assert server._check_allowed("telegram", "111") is True

    def test_check_allowed_telegram_denied(self, tmp_path):
        config = GatewayConfig(
            telegram=TelegramConfig(enabled=True, allowed_users=[111])
        )
        server = _make_server(config, tmp_path)
        assert server._check_allowed("telegram", "999") is False

    def test_check_allowed_discord_string_id(self, tmp_path):
        config = GatewayConfig(
            discord=DiscordConfig(enabled=True, allowed_users=["alice"])
        )
        server = _make_server(config, tmp_path)
        assert server._check_allowed("discord", "alice") is True

    def test_check_allowed_unknown_platform(self, tmp_path):
        config = GatewayConfig(telegram=TelegramConfig(enabled=True))
        server = _make_server(config, tmp_path)
        assert server._check_allowed("matrix", "someone") is False


# ---------------------------------------------------------------------------
# GatewayServer handle_message
# ---------------------------------------------------------------------------


def _make_mock_agent_loop():
    """Create a mock AgentLoop whose run() yields text_delta + done events."""
    loop = MagicMock()

    async def _run(messages):
        yield {"type": "text_delta", "text": "Hello"}
        yield {"type": "done", "stop_reason": "end_turn"}

    loop.run = _run
    return loop


class TestGatewayServerHandleMessage:
    @pytest.mark.asyncio
    async def test_handle_message_unauthorized(self, tmp_path):
        config = GatewayConfig(
            telegram=TelegramConfig(enabled=True, allowed_users=[111])
        )
        server = _make_server(config, tmp_path)
        result = await server.handle_message("telegram", "999", "hi")
        assert "not authorized" in result.lower()

    @pytest.mark.asyncio
    async def test_handle_message_reset_command(self, tmp_path):
        config = GatewayConfig(telegram=TelegramConfig(enabled=True))
        server = _make_server(config, tmp_path)
        result = await server.handle_message("telegram", "123", "/new")
        assert "reset" in result.lower()
        assert "fresh" in result.lower()

    @pytest.mark.asyncio
    async def test_handle_message_reset_slash_reset(self, tmp_path):
        config = GatewayConfig(telegram=TelegramConfig(enabled=True))
        server = _make_server(config, tmp_path)
        result = await server.handle_message("telegram", "123", "/reset")
        assert "reset" in result.lower()

    def test_get_status_not_running(self, tmp_path):
        config = GatewayConfig()
        server = _make_server(config, tmp_path)
        status = server.get_status()
        assert status["running"] is False
        assert status["adapters"] == {}

    @pytest.mark.asyncio
    async def test_get_status_after_start(self, tmp_path):
        config = GatewayConfig()
        server = _make_server(config, tmp_path)
        await server.start()
        status = server.get_status()
        assert status["running"] is True
        # No adapters configured, so still empty
        assert status["adapters"] == {}
        await server.stop()
