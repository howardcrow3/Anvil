"""Platform adapters for the Anvil Messaging Gateway."""

from __future__ import annotations

from anvil_agent.gateway.adapters.base import PlatformAdapter

__all__ = ["PlatformAdapter"]

# Conditional exports - only available if dependencies are installed
try:
    from anvil_agent.gateway.adapters.telegram import TelegramAdapter
    __all__.append("TelegramAdapter")
except ImportError:
    pass

try:
    from anvil_agent.gateway.adapters.discord import DiscordAdapter
    __all__.append("DiscordAdapter")
except ImportError:
    pass

try:
    from anvil_agent.gateway.adapters.slack import SlackAdapter
    __all__.append("SlackAdapter")
except ImportError:
    pass

try:
    from anvil_agent.gateway.adapters.webhook import WebhookAdapter
    __all__.append("WebhookAdapter")
except ImportError:
    pass
