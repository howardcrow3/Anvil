"""Execute shell commands tool."""

from __future__ import annotations

import asyncio
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
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )

            parts = []
            if stdout:
                parts.append(stdout.decode("utf-8", errors="replace"))
            if stderr:
                parts.append(f"STDERR:\n{stderr.decode('utf-8', errors='replace')}")
            parts.append(f"Exit code: {proc.returncode}")

            return ToolResult(
                id="",
                content="\n".join(parts),
                is_error=proc.returncode != 0,
            )
        except asyncio.TimeoutError:
            return ToolResult(
                id="",
                content=f"Error: Command timed out after {timeout}s",
                is_error=True,
            )
        except Exception as e:
            return ToolResult(id="", content=f"Error: {e}", is_error=True)
