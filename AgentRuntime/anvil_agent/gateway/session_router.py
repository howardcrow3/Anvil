"""Session routing for multi-platform gateway."""

from __future__ import annotations

import logging
from typing import Any

from anvil_agent.models.types import ChatMessage
from anvil_agent.session.manager import SessionManager

logger = logging.getLogger(__name__)


class SessionRouter:
    """Maps platform user IDs to agent sessions."""

    def __init__(self, session_manager: SessionManager) -> None:
        self._session_manager = session_manager
        self._session_map: dict[str, str] = {}  # "platform:user_id" -> session_id

    def _key(self, platform: str, user_id: str) -> str:
        return f"{platform}:{user_id}"

    def get_or_create_session(
        self, platform: str, user_id: str
    ) -> tuple[str, list[ChatMessage]]:
        """Get existing session or create a new one.

        Returns (session_id, existing_messages).
        """
        key = self._key(platform, user_id)
        session_id = self._session_map.get(key)

        if session_id is not None:
            messages = self._session_manager.load_messages(session_id)
            return session_id, messages

        session_id = self._session_manager.create(name=f"{platform}/{user_id}")
        self._session_map[key] = session_id
        logger.info("Created session %s for %s", session_id, key)
        return session_id, []

    def reset_session(self, platform: str, user_id: str) -> None:
        """Reset a user's session, creating a fresh one next time."""
        key = self._key(platform, user_id)
        self._session_map.pop(key, None)
        logger.info("Reset session for %s", key)

    def save_message(
        self, platform: str, user_id: str, message: ChatMessage
    ) -> None:
        """Save a message to the user's session."""
        key = self._key(platform, user_id)
        session_id = self._session_map.get(key)
        if session_id:
            self._session_manager.append_message(session_id, message)
