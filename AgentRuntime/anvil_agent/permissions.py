"""Permission model for tool execution."""

from __future__ import annotations

import asyncio
import logging
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

READ_ONLY_TOOLS = {"read_file", "glob", "grep", "web_search", "web_fetch", "ask_user"}


class PermissionMode(str, Enum):
    ASK = "ask"
    ACCEPT_EDITS = "accept_edits"
    TRUST = "trust"


class PermissionManager:
    """Manages tool-execution permissions with per-tool overrides."""

    def __init__(self, mode: PermissionMode = PermissionMode.ASK) -> None:
        self._mode = mode
        self._allow_list: set[str] = set()
        self._deny_list: set[str] = set()
        self._pending: dict[str, asyncio.Event] = {}
        self._responses: dict[str, bool] = {}

    @property
    def mode(self) -> PermissionMode:
        return self._mode

    @mode.setter
    def mode(self, value: PermissionMode) -> None:
        self._mode = value

    def set_overrides(
        self,
        allow_list: list[str] | None = None,
        deny_list: list[str] | None = None,
    ) -> None:
        """Configure per-tool allow/deny overrides."""
        if allow_list:
            self._allow_list = set(allow_list)
        if deny_list:
            self._deny_list = set(deny_list)

    def check_sync(self, tool_name: str) -> str:
        """Check permission for a tool synchronously.

        Returns 'allow', 'deny', or 'ask'.
        """
        if tool_name in self._deny_list:
            return "deny"
        if tool_name in self._allow_list:
            return "allow"

        match self._mode:
            case PermissionMode.TRUST:
                return "allow"
            case PermissionMode.ACCEPT_EDITS:
                if tool_name in READ_ONLY_TOOLS:
                    return "allow"
                return "ask"
            case PermissionMode.ASK:
                return "ask"
        return "ask"

    async def request_permission(
        self, request_id: str, tool_name: str, arguments: dict[str, Any]
    ) -> bool:
        """Wait for user to approve or deny a tool call.

        Returns True if approved, False if denied or timed out.
        """
        event = asyncio.Event()
        self._pending[request_id] = event

        try:
            await asyncio.wait_for(event.wait(), timeout=300)
        except asyncio.TimeoutError:
            self._pending.pop(request_id, None)
            return False

        self._pending.pop(request_id, None)
        return self._responses.pop(request_id, False)

    def respond(self, request_id: str, approved: bool) -> None:
        """Called when user responds to a permission request."""
        self._responses[request_id] = approved
        if request_id in self._pending:
            self._pending[request_id].set()
