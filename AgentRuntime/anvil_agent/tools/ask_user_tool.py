"""Ask user a question tool."""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Coroutine

from anvil_agent.models.types import ToolResult
from anvil_agent.tools.base import Tool


class AskUserTool(Tool):
    name = "ask_user"
    description = "Ask the user a question and wait for their response."
    requires_approval = False
    parameters = {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The question to ask the user.",
            },
        },
        "required": ["question"],
    }

    def __init__(self) -> None:
        self._callback: Callable[[str], Coroutine[Any, Any, str]] | None = None
        self._pending_future: asyncio.Future[str] | None = None

    def set_callback(self, callback: Callable[[str], Coroutine[Any, Any, str]]) -> None:
        """Set the callback that sends the question via IPC and waits for user response."""
        self._callback = callback

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        question = arguments["question"]

        if self._callback:
            try:
                answer = await self._callback(question)
                return ToolResult(id="", content=answer)
            except Exception as e:
                return ToolResult(id="", content=f"Error: {e}", is_error=True)

        return ToolResult(
            id="",
            content="[User interaction not available in current mode]",
            is_error=True,
        )
