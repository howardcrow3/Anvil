"""Hooks engine - executes lifecycle hooks."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from enum import Enum
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

GLOBAL_HOOKS_PATH = Path.home() / ".anvil" / "hooks.json"


class HookEvent(str, Enum):
    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    USER_PROMPT_SUBMIT = "UserPromptSubmit"
    PRE_COMPACT = "PreCompact"
    POST_COMPACT = "PostCompact"
    SESSION_START = "SessionStart"
    SESSION_END = "SessionEnd"
    STOP = "Stop"


class HooksEngine:
    """Executes configured hooks at lifecycle events."""

    def __init__(self, hooks_config: list[dict[str, Any]] | None = None) -> None:
        self._hooks: list[dict[str, Any]] = hooks_config or []

    def load_config(self, config: list[dict[str, Any]]) -> None:
        self._hooks = config

    def load_from_files(self, project_dir: Path | None = None) -> None:
        """Load hooks from global and project-level config files."""
        hooks: list[dict[str, Any]] = []

        # Global hooks
        if GLOBAL_HOOKS_PATH.exists():
            try:
                raw = json.loads(GLOBAL_HOOKS_PATH.read_text(encoding="utf-8"))
                if isinstance(raw, list):
                    hooks.extend(raw)
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Failed to load global hooks: %s", exc)

        # Project-level hooks
        if project_dir:
            hooks_dir = project_dir / ".claude" / "hooks"
            if hooks_dir.is_dir():
                for path in sorted(hooks_dir.glob("*.json")):
                    try:
                        raw = json.loads(path.read_text(encoding="utf-8"))
                        if isinstance(raw, list):
                            hooks.extend(raw)
                        elif isinstance(raw, dict):
                            hooks.append(raw)
                    except (json.JSONDecodeError, OSError) as exc:
                        logger.warning("Failed to load hook file %s: %s", path, exc)

        self._hooks = hooks

    def _matches(self, hook: dict[str, Any], data: dict[str, Any]) -> bool:
        """Check if a hook's matcher criteria are satisfied."""
        matcher = hook.get("matcher")
        if not matcher:
            return True

        if "tool_name" in matcher:
            if data.get("tool_name") != matcher["tool_name"]:
                return False

        if "regex" in matcher:
            try:
                if not re.search(matcher["regex"], json.dumps(data)):
                    return False
            except re.error as exc:
                logger.warning("Invalid matcher regex: %s", exc)
                return False

        return True

    async def run(
        self, event: HookEvent, data: dict[str, Any]
    ) -> tuple[bool, str | None]:
        """Run all hooks for an event.

        Returns (allowed, output) where allowed is False if blocked and output
        is the concatenated stdout from command hooks.
        """
        collected_output: list[str] = []

        for hook in self._hooks:
            if hook.get("event") != event.value:
                continue

            if not self._matches(hook, data):
                continue

            hook_type = hook.get("type", "command")
            try:
                match hook_type:
                    case "command":
                        allowed, stdout = await self._run_command_hook(hook, data)
                        if stdout:
                            collected_output.append(stdout)
                    case "http":
                        allowed = await self._run_http_hook(hook, data)
                    case _:
                        logger.warning("Unknown hook type: %s", hook_type)
                        continue

                if not allowed:
                    logger.info("Hook blocked event %s", event.value)
                    output = "\n".join(collected_output) if collected_output else None
                    return False, output
            except Exception as e:
                logger.error("Hook error for %s: %s", event.value, e)

        output = "\n".join(collected_output) if collected_output else None
        return True, output

    async def _run_command_hook(
        self, hook: dict[str, Any], data: dict[str, Any]
    ) -> tuple[bool, str | None]:
        """Run a shell command hook. Exit code 0=allow, 2=block.

        Returns (allowed, stdout_text).
        """
        command = hook.get("command", "")
        if not command:
            return True, None

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

        stdout_text = stdout.decode(errors="replace").strip() if stdout else None
        allowed = proc.returncode != 2
        return allowed, stdout_text or None

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
