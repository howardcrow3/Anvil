"""Write file tool."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from anvil_agent.models.types import ToolResult
from anvil_agent.tools.base import Tool


class WriteTool(Tool):
    name = "write_file"
    description = "Create or overwrite a file with the given content. Creates parent directories if needed."
    requires_approval = True
    parameters = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Absolute path to the file to write.",
            },
            "content": {
                "type": "string",
                "description": "The content to write to the file.",
            },
        },
        "required": ["file_path", "content"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        file_path = Path(arguments["file_path"])
        content = arguments["content"]

        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            return ToolResult(
                id="",
                content=f"Successfully wrote {len(content)} bytes to {file_path}",
            )
        except Exception as e:
            return ToolResult(id="", content=f"Error writing file: {e}", is_error=True)
