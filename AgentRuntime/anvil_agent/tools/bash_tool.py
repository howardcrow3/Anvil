"""Execute shell commands tool."""

from __future__ import annotations

import asyncio
import os
import signal
from typing import Any

from anvil_agent.models.types import ToolResult
from anvil_agent.tools.base import Tool


class BashTool(Tool):
    name = "bash"
    description = "Execute a shell command and return its output (stdout, stderr, exit code)."
    requires_approval = True
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute.",
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds. Default 120.",
                "default": 120,
            },
            "working_dir": {
                "type": "string",
                "description": "Working directory for the command. Optional.",
            },
        },
        "required": ["command"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        command = arguments["command"]
        timeout = arguments.get("timeout", 120)
        working_dir = arguments.get("working_dir")

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir,
                # Own process group, so a timeout or cancel can take the whole tree down.
                start_new_session=(os.name == "posix"),
            )
        except Exception as e:
            return ToolResult(id="", content=f"Error: {e}", is_error=True)

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            await _kill_tree(proc)
            return ToolResult(id="", content=f"Error: Command timed out after {timeout}s", is_error=True)
        except BaseException:
            # Cancelled (user pressed stop) or interrupted: never leave the command running.
            await _kill_tree(proc)
            raise

        # Exit code first, and each stream capped on its own keeping the tail: the caller truncates the
        # joined text from the head, so a noisy stdout must not push the failure signal off the end.
        parts = [f"Exit code: {proc.returncode}"]
        if stdout:
            parts.append(_tail(stdout.decode("utf-8", errors="replace")))
        if stderr:
            parts.append("STDERR:\n" + _tail(stderr.decode("utf-8", errors="replace")))
        return ToolResult(id="", content="\n".join(parts), is_error=proc.returncode != 0)


STREAM_LIMIT = 4000


def _tail(text: str, limit: int = STREAM_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return f"[... {len(text) - limit} characters omitted ...]\n{text[-limit:]}"


async def _kill_tree(proc: asyncio.subprocess.Process) -> None:
    """Kill the shell and everything it started, then reap it."""
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGKILL)
        else:  # no process groups on Windows: taskkill /T walks the child tree
            killer = await asyncio.create_subprocess_exec(
                "taskkill", "/F", "/T", "/PID", str(proc.pid),
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            )
            await killer.wait()
    except (ProcessLookupError, PermissionError, OSError):
        pass
    try:
        proc.kill()
    except ProcessLookupError:
        pass
    try:
        await asyncio.wait_for(proc.wait(), timeout=5)
    except asyncio.TimeoutError:
        pass
