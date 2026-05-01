"""Read file contents tool."""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any

from anvil_agent.models.types import ToolResult
from anvil_agent.tools.base import Tool


class ReadTool(Tool):
    name = "read_file"
    description = "Read the contents of a file. Returns file contents with line numbers."
    requires_approval = False
    parameters = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Absolute path to the file to read.",
            },
            "offset": {
                "type": "integer",
                "description": "Line number to start reading from (1-based). Optional.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of lines to read. Optional.",
            },
        },
        "required": ["file_path"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        file_path = Path(arguments["file_path"])
        offset = arguments.get("offset", 1)
        limit = arguments.get("limit")

        if not file_path.exists():
            return ToolResult(id="", content=f"Error: File not found: {file_path}", is_error=True)

        if not file_path.is_file():
            return ToolResult(id="", content=f"Error: Not a file: {file_path}", is_error=True)

        mime_type, _ = mimetypes.guess_type(str(file_path))
        if mime_type and not mime_type.startswith("text") and mime_type not in (
            "application/json",
            "application/xml",
            "application/javascript",
            "application/x-yaml",
        ):
            return ToolResult(
                id="",
                content=f"Binary file ({mime_type}): {file_path} ({file_path.stat().st_size} bytes)",
            )

        try:
            text = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return ToolResult(id="", content=f"Error reading file: {e}", is_error=True)

        lines = text.splitlines()
        start = max(0, offset - 1)
        end = start + limit if limit else len(lines)
        selected = lines[start:end]

        numbered = []
        for i, line in enumerate(selected, start=start + 1):
            truncated = line[:2000] + "..." if len(line) > 2000 else line
            numbered.append(f"{i:>6}\t{truncated}")

        return ToolResult(id="", content="\n".join(numbered))
