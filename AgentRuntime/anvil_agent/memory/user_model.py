"""User modeling - maintains a persistent profile of the user."""

from __future__ import annotations

import logging
from pathlib import Path

from anvil_agent.models.types import ChatMessage

logger = logging.getLogger(__name__)

USER_MD_PATH = Path.home() / ".anvil" / "memory" / "USER.md"

DEFAULT_USER_MD = """\
# User Profile

## Identity

## Preferences

## Skills

## Communication Style

## Workflow
"""

MAX_CONTEXT_CHARS = 1000


class UserModelManager:
    """Maintains ~/.anvil/memory/USER.md as a persistent user profile."""

    def __init__(self, path: Path = USER_MD_PATH) -> None:
        self._path = path
        self._ensure_file()

    def _ensure_file(self) -> None:
        """Create USER.md with default template if it doesn't exist."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._path.write_text(DEFAULT_USER_MD, encoding="utf-8")

    def load_user_context(self) -> str:
        """Return USER.md content, truncated to MAX_CONTEXT_CHARS."""
        try:
            content = self._path.read_text(encoding="utf-8")
            if len(content) > MAX_CONTEXT_CHARS:
                content = content[:MAX_CONTEXT_CHARS] + "\n... (truncated)"
            return content
        except Exception as e:
            logger.warning("Failed to read USER.md: %s", e)
            return ""

    async def update_from_conversation(self, messages: list[ChatMessage]) -> None:
        """Extract user insights from conversation.

        This is a template for future LLM-based extraction. Currently logs only.
        """
        user_messages = [m for m in messages if m.role == "user" and m.content]
        if not user_messages:
            return
        logger.info(
            "User model update candidate: %d user messages in conversation",
            len(user_messages),
        )

    def get_system_prompt_addition(self) -> str:
        """Return user profile formatted for system prompt injection."""
        content = self.load_user_context()
        if not content or content.strip() == DEFAULT_USER_MD.strip():
            return ""
        return f"# User Profile\n{content}"
