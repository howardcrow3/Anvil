"""Hooks engine - executes lifecycle hooks."""

from __future__ import annotations

import asyncio
import json
import logging
from enum import Enum
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class HookEvent(str, Enum):
    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    SESSION_START = "SessionStart"
    SESSION_END = "SessionEnd"
    STOP = "Stop"


class HooksEngine:
    """Executes configured hooks at lifecycle events."""

    def __init__(self, hooks_config: list[dict[str, Any]] | None = None) -> None:
        self._hooks = hooks_config or []

    def load_config(self, config: list[dict[str, Any]]) -> None:
        self._hooks = config

    async def run(self, event: HookEvent, data: dict[str, Any]) -> bool:
        """Run all hooks for an event.

        Returns True if execution should proceed, False if blocked.
        """
        for hook in self._hooks:
            if hook.get("event") != event.value:
                continue

            hook_type = hook.get("type", "command")
            try:
                match hook_type:
                    case "command":
                        allowed = await self._run_command_hook(hook, data)
                    case "http":
                        allowed = await self._run_http_hook(hook, data)
                    case _:
                        logger.warning("Unknown hook type: %s", hook_type)
                        continue

                if not allowed:
                    logger.info("Hook blocked event %s", event.value)
                    return False
            except Exception as e:
                logger.error("Hook error for %s: %s", event.value, e)

        return True

    async def _run_command_hook(
        self, hook: dict[str, Any], data: dict[str, Any]
    ) -> bool:
        """Run a shell command hook. Exit code 0=allow, 2=block."""
        command = hook.get("command", "")
        if not command:
            return True

        proc = await asyncio.create_subprocess_shell(
            command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=json.dumps(data).encode()),
            timeout=30,
        )

        if proc.returncode == 2:
            return False
        return True

    async def _run_http_hook(
        self, hook: dict[str, Any], data: dict[str, Any]
    ) -> bool:
        """Run an HTTP POST hook."""
        url = hook.get("url", "")
        if not url:
            return True

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=data)
            if resp.status_code == 403:
                return False
        return True
