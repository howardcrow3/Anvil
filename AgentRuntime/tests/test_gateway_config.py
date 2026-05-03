"""Tests for gateway configuration models and persistence."""

import json

import pytest

from anvil_agent.gateway.config import (
    DiscordConfig,
    GatewayConfig,
    SlackConfig,
    TelegramConfig,
    WebhookConfig,
    load_gateway_config,
    save_gateway_config,
)


# ---------------------------------------------------------------------------
# Platform config defaults
# ---------------------------------------------------------------------------


class TestPlatformConfigs:
    def test_telegram_defaults(self):
        cfg = TelegramConfig()
        assert cfg.enabled is False
        assert cfg.session_reset == "daily"
        assert cfg.bot_token == ""
        assert cfg.allowed_users == []

    def test_discord_defaults(self):
        cfg = DiscordConfig()
        assert cfg.enabled is False
        assert cfg.session_reset == "daily"
        assert cfg.bot_token == ""
        assert cfg.allowed_users == []

    def test_slack_defaults(self):
        cfg = SlackConfig()
        assert cfg.enabled is False
        assert cfg.session_reset == "daily"
        assert cfg.bot_token == ""
        assert cfg.app_token == ""
        assert cfg.allowed_users == []

    def test_webhook_defaults(self):
        cfg = WebhookConfig()
        assert cfg.enabled is False
        assert cfg.session_reset == "daily"
        assert cfg.port == 8432
        assert cfg.hmac_secret == ""

    def test_telegram_custom_values(self):
        cfg = TelegramConfig(
            enabled=True,
            session_reset="never",
            bot_token="tok123",
            allowed_users=[111, 222],
        )
        assert cfg.enabled is True
        assert cfg.session_reset == "never"
        assert cfg.bot_token == "tok123"
        assert cfg.allowed_users == [111, 222]

    def test_gateway_config_defaults(self):
        cfg = GatewayConfig()
        assert cfg.telegram is None
        assert cfg.discord is None
        assert cfg.slack is None
        assert cfg.webhook is None


# ---------------------------------------------------------------------------
# Config persistence
# ---------------------------------------------------------------------------


class TestGatewayConfigPersistence:
    def test_load_missing_file(self, tmp_path):
        cfg = load_gateway_config(path=tmp_path / "nonexistent.json")
        assert cfg == GatewayConfig()

    def test_save_and_load(self, tmp_path):
        path = tmp_path / "gateway.json"
        original = GatewayConfig(
            telegram=TelegramConfig(enabled=True, bot_token="abc"),
            discord=DiscordConfig(allowed_users=["u1"]),
        )
        save_gateway_config(original, path=path)
        loaded = load_gateway_config(path=path)
        assert loaded == original

    def test_load_invalid_json(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("not valid json {{{")
        cfg = load_gateway_config(path=path)
        assert cfg == GatewayConfig()

    def test_save_creates_parent_dirs(self, tmp_path):
        path = tmp_path / "a" / "b" / "c" / "gateway.json"
        save_gateway_config(GatewayConfig(), path=path)
        assert path.exists()
