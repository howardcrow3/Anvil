"""Edit file tool."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from anvil_agent.models.types import ToolResult
from anvil_agent.tools.base import Tool, resolve_path


class EditTool(Tool):
    name = "edit_file"
    description = (
        "Edit an existing file by replacing a specific string. "
        "The old_string must exist in the file and be unique (unless replace_all is true)."
    )
    requires_approval = True
    parameters = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Absolute path to the file to edit.",
            },
            "old_string": {
                "type": "string",
                "description": "The exact string to find and replace.",
            },
            "new_string": {
                "type": "string",
                "description": "The string to replace it with.",
            },
            "replace_all": {
                "type": "boolean",
                "description": "If true, replace all occurrences. Default false.",
                "default": False,
            },
        },
        "required": ["file_path", "old_string", "new_string"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        file_path = resolve_path(arguments)
        old_string = arguments["old_string"]
        new_string = arguments["new_string"]
        replace_all = arguments.get("replace_all", False)

        if not file_path.exists():
            return ToolResult(id="", content=f"Error: File not found: {file_path}", is_error=True)

        try:
            # newline="" keeps the file's own line endings; text mode would silently turn CRLF into LF.
            with open(file_path, encoding="utf-8", newline="") as f:
                content = f.read()
        except Exception as e:
            return ToolResult(id="", content=f"Error reading file: {e}", is_error=True)

        # A file that is entirely CRLF is matched and edited as LF (that is how the model writes it),
        # then converted back, so one edit never changes the line endings of the whole file.
        crlf = "\r\n" in content and "\n" not in content.replace("\r\n", "")
        if crlf:
            content = content.replace("\r\n", "\n")

        count = content.count(old_string)
        if count == 0:
            return ToolResult(
                id="",
                content=f"Error: old_string not found in {file_path}",
                is_error=True,
            )
        if count > 1 and not replace_all:
            return ToolResult(
                id="",
                content=f"Error: old_string found {count} times. Use replace_all=true or provide more context.",
                is_error=True,
            )

        if replace_all:
            new_content = content.replace(old_string, new_string)
            replacements = count
        else:
            new_content = content.replace(old_string, new_string, 1)
            replacements = 1

        if crlf:
            new_content = new_content.replace("\n", "\r\n")
        try:
            with open(file_path, "w", encoding="utf-8", newline="") as f:
                f.write(new_content)
            return ToolResult(
                id="",
                content=f"Replaced {replacements} occurrence(s) in {file_path}",
            )
        except Exception as e:
            return ToolResult(id="", content=f"Error writing file: {e}", is_error=True)
