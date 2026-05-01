"""Slash-command execution."""

from __future__ import annotations

import logging
from typing import Any

from anvil_agent.models.types import ChatMessage
from anvil_agent.skills.loader import SkillLoader

logger = logging.getLogger(__name__)


class SkillExecutor:
    """Handles slash commands from user input."""

    def __init__(
        self,
        loader: SkillLoader,
        session_manager: Any,
        settings_manager: Any,
    ) -> None:
        self._loader = loader
        self._session_manager = session_manager
        self._settings = settings_manager

    async def handle_command(
        self, command: str, messages: list[ChatMessage]
    ) -> dict[str, Any] | None:
        """Handle a slash command. Returns response dict or None if not a command."""
        if not command.startswith("/"):
            return None

        parts = command.split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        match cmd:
            case "/help":
                return self._help()
            case "/clear":
                return self._clear(messages)
            case "/compact":
                return await self._compact(messages)
            case "/settings":
                return self._show_settings()
            case "/plan":
                return {"action": "toggle_plan_mode"}
            case "/resume":
                return {"action": "resume_last_session"}
            case _:
                # Check custom commands
                custom = self._loader.get_command(cmd)
                if custom and not custom.get("builtin"):
                    return {
                        "action": "inject_skill",
                        "text": custom.get("content", ""),
                    }
                return {"action": "unknown", "text": f"Unknown command: {cmd}"}

    def _help(self) -> dict[str, Any]:
        """Return formatted help text with all commands."""
        commands = self._loader.get_all_commands()
        lines = ["Available commands:", ""]
        for cmd in commands:
            tag = "" if cmd.get("builtin") else " (custom)"
            lines.append(f"  {cmd['name']:12s}  {cmd['description']}{tag}")
        return {"action": "help", "text": "\n".join(lines)}

    def _clear(self, messages: list[ChatMessage]) -> dict[str, Any]:
        """Clear the conversation history."""
        messages.clear()
        return {"action": "cleared", "text": "Conversation cleared."}

    async def _compact(self, messages: list[ChatMessage]) -> dict[str, Any]:
        """Summarize old messages, keep the last 5."""
        if len(messages) <= 5:
            return {"action": "compacted", "text": "Nothing to compact."}

        old_count = len(messages) - 5
        # Build a summary of older messages
        summary_parts: list[str] = []
        for msg in messages[:old_count]:
            prefix = msg.role.upper()
            content = msg.content[:200] if msg.content else ""
            summary_parts.append(f"[{prefix}] {content}")

        summary_text = "\n".join(summary_parts)
        summary_msg = ChatMessage(
            role="system",
            content=f"[Compacted {old_count} earlier messages]\n{summary_text}",
        )

        kept = messages[-5:]
        messages.clear()
        messages.append(summary_msg)
        messages.extend(kept)

        return {
            "action": "compacted",
            "text": f"Compacted {old_count} messages into summary.",
        }

    def _show_settings(self) -> dict[str, Any]:
        """Return current settings as formatted text."""
        all_settings = self._settings.get_all()
        lines = ["Current settings:", ""]
        for key, value in all_settings.items():
            # Mask the api key
            display = "****" if key == "api_key" and value else value
            lines.append(f"  {key}: {display}")
        return {"action": "settings", "text": "\n".join(lines)}
