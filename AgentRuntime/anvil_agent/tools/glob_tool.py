"""Glob file search tool."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from anvil_agent.models.types import ToolResult
from anvil_agent.tools.base import Tool


class GlobTool(Tool):
    name = "glob"
    description = "Find files matching a glob pattern. Returns sorted list of matching file paths."
    requires_approval = False
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Glob pattern (e.g. '**/*.py', 'src/**/*.ts').",
            },
            "path": {
                "type": "string",
                "description": "Directory to search in. Defaults to current working directory.",
            },
        },
        "required": ["pattern"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        pattern = arguments["pattern"]
        search_path = Path(arguments.get("path", "."))

        if not search_path.exists():
            return ToolResult(id="", content=f"Error: Path not found: {search_path}", is_error=True)

        try:
            matches = sorted(str(p) for p in search_path.glob(pattern) if p.is_file())
            if not matches:
                return ToolResult(id="", content="No files matched the pattern.")
            return ToolResult(id="", content="\n".join(matches))
        except Exception as e:
            return ToolResult(id="", content=f"Error: {e}", is_error=True)
