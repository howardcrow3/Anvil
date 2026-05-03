"""Gateway configuration models and persistence."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

GATEWAY_CONFIG_PATH = Path.home() / ".anvil" / "gateway.json"


class PlatformConfig(BaseModel):
    """Base configuration for a platform adapter."""

    enabled: bool = False
    session_reset: Literal["daily", "never", "per_conversation"] = "daily"


class TelegramConfig(PlatformConfig):
    """Telegram bot configuration."""

    bot_token: str = ""
    allowed_users: list[int] = Field(default_factory=list)


class DiscordConfig(PlatformConfig):
    """Discord bot configuration."""

    bot_token: str = ""
    allowed_users: list[str] = Field(default_factory=list)


class SlackConfig(PlatformConfig):
    """Slack bot configuration."""

    bot_token: str = ""
    app_token: str = ""
    allowed_users: list[str] = Field(default_factory=list)


class WebhookConfig(PlatformConfig):
    """Webhook server configuration."""

    port: int = 8432
    hmac_secret: str = ""


class GatewayConfig(BaseModel):
    """Top-level gateway configuration."""

    telegram: TelegramConfig | None = None
    discord: DiscordConfig | None = None
    slack: SlackConfig | None = None
    webhook: WebhookConfig | None = None


def load_gateway_config(path: Path = GATEWAY_CONFIG_PATH) -> GatewayConfig:
    """Load gateway configuration from ~/.anvil/gateway.json."""
    if not path.exists():
        return GatewayConfig()
    try:
        raw = json.loads(path.read_text())
        return GatewayConfig(**raw)
    except (json.JSONDecodeError, Exception) as exc:
        logger.warning("Failed to load gateway config: %s", exc)
        return GatewayConfig()


def save_gateway_config(
    config: GatewayConfig, path: Path = GATEWAY_CONFIG_PATH
) -> None:
    """Save gateway configuration to ~/.anvil/gateway.json."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(config.model_dump_json(indent=2) + "\n")
