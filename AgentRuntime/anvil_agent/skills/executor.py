"""Slash-command execution."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from anvil_agent.models.types import ChatMessage
from anvil_agent.skills.loader import SkillLoader

if TYPE_CHECKING:
    from anvil_agent.skills.improver import SkillImprover

logger = logging.getLogger(__name__)


class SkillExecutor:
    """Handles slash commands from user input."""

    def __init__(
        self,
        loader: SkillLoader,
        session_manager: Any,
        settings_manager: Any,
        improver: SkillImprover | None = None,
    ) -> None:
        self._loader = loader
        self._session_manager = session_manager
        self._settings = settings_manager
        self._improver = improver

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
            case "/skills":
                return self._handle_skills(args)
            case _:
                # Check custom commands
                custom = self._loader.get_command(cmd)
                if custom and not custom.get("builtin"):
                    # Notify improver that a skill is being executed
                    if self._improver:
                        self._improver.set_active_skill(
                            cmd.lstrip("/"),
                            custom.get("content", ""),
                        )
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

    def _handle_skills(self, args: str) -> dict[str, Any]:
        """Handle /skills browse and /skills search <query>."""
        parts = args.strip().split(maxsplit=1)
        subcmd = parts[0].lower() if parts else "browse"

        if subcmd == "search" and len(parts) > 1:
            query = parts[1]
            from anvil_agent.skills.hub import SkillsHub
            hub = SkillsHub(self._loader)
            results = hub.search(query)
            if not results:
                return {"action": "skills", "text": f"No skills found for '{query}'."}
            lines = [f"Skills matching '{query}':", ""]
            for s in results:
                src = s.get("source", "?")
                ver = s.get("version", "")
                lines.append(f"  {s['name']:20s}  [{src}]  v{ver}  {s.get('description', '')}")
            return {"action": "skills", "text": "\n".join(lines)}

        # Default: browse
        from anvil_agent.skills.hub import SkillsHub
        hub = SkillsHub(self._loader)
        all_skills = hub.browse()
        if not all_skills:
            return {"action": "skills", "text": "No skills found."}
        lines = ["Available skills:", ""]
        for s in all_skills:
            src = s.get("source", "?")
            ver = s.get("version", "")
            lines.append(f"  {s['name']:20s}  [{src}]  v{ver}  {s.get('description', '')}")
        return {"action": "skills", "text": "\n".join(lines)}
