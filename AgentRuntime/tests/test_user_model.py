"""Tests for anvil_agent.memory.user_model."""

from __future__ import annotations

import pytest

from anvil_agent.memory.user_model import (
    DEFAULT_USER_MD,
    MAX_CONTEXT_CHARS,
    UserModelManager,
)
from anvil_agent.models.types import ChatMessage


class TestUserModelManager:
    """Tests for UserModelManager."""

    def test_creates_default_file(self, tmp_path):
        path = tmp_path / "memory" / "USER.md"
        UserModelManager(path=path)
        assert path.exists()
        assert path.read_text(encoding="utf-8") == DEFAULT_USER_MD

    def test_load_user_context(self, tmp_path):
        path = tmp_path / "USER.md"
        custom = "# My Custom Profile\nSome info about me."
        path.write_text(custom, encoding="utf-8")
        mgr = UserModelManager(path=path)
        assert mgr.load_user_context() == custom

    def test_load_user_context_truncation(self, tmp_path):
        path = tmp_path / "USER.md"
        long_content = "x" * (MAX_CONTEXT_CHARS + 500)
        path.write_text(long_content, encoding="utf-8")
        mgr = UserModelManager(path=path)
        result = mgr.load_user_context()
        assert len(result) < len(long_content)
        assert result.endswith("\n... (truncated)")
        assert result.startswith("x" * 100)

    def test_get_system_prompt_addition_default(self, tmp_path):
        path = tmp_path / "USER.md"
        mgr = UserModelManager(path=path)
        assert mgr.get_system_prompt_addition() == ""

    def test_get_system_prompt_addition_custom(self, tmp_path):
        path = tmp_path / "USER.md"
        custom = "# Custom\nI prefer dark mode."
        path.write_text(custom, encoding="utf-8")
        mgr = UserModelManager(path=path)
        result = mgr.get_system_prompt_addition()
        assert result == f"# User Profile\n{custom}"

    @pytest.mark.asyncio
    async def test_update_from_conversation(self, tmp_path):
        path = tmp_path / "USER.md"
        mgr = UserModelManager(path=path)
        messages = [
            ChatMessage(role="user", content="hello"),
            ChatMessage(role="assistant", content="hi there"),
        ]
        await mgr.update_from_conversation(messages)

    @pytest.mark.asyncio
    async def test_update_from_conversation_no_user_messages(self, tmp_path):
        path = tmp_path / "USER.md"
        mgr = UserModelManager(path=path)
        messages = [
            ChatMessage(role="assistant", content="I can help with that."),
        ]
        await mgr.update_from_conversation(messages)

    def test_existing_file_not_overwritten(self, tmp_path):
        path = tmp_path / "USER.md"
        custom = "# Existing content\nDo not overwrite me."
        path.write_text(custom, encoding="utf-8")
        UserModelManager(path=path)
        assert path.read_text(encoding="utf-8") == custom
