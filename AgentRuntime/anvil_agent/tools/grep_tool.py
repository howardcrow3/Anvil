"""Grep tool for searching file contents."""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from typing import Any

from anvil_agent.models.types import ToolResult
from anvil_agent.tools.base import Tool


class GrepTool(Tool):
    name = "grep"
    description = "Search file contents using regex. Returns matches in file:line:content format."
    requires_approval = False
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Regex pattern to search for.",
            },
            "path": {
                "type": "string",
                "description": "Directory to search in. Defaults to current working directory.",
            },
            "include": {
                "type": "string",
                "description": "File glob pattern to filter which files to search (e.g. '*.py').",
            },
        },
        "required": ["pattern"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        pattern = arguments["pattern"]
        search_path = Path(arguments.get("path", "."))
        include = arguments.get("include", "*")

        try:
            regex = re.compile(pattern)
        except re.error as e:
            return ToolResult(id="", content=f"Error: Invalid regex: {e}", is_error=True)

        if not search_path.exists():
            return ToolResult(id="", content=f"Error: Path not found: {search_path}", is_error=True)

        matches: list[str] = []
        max_results = 200

        files = sorted(search_path.rglob("*"))
        for fpath in files:
            if not fpath.is_file():
                continue
            if not fnmatch.fnmatch(fpath.name, include):
                continue
            try:
                text = fpath.read_text(encoding="utf-8", errors="replace")
                for lineno, line in enumerate(text.splitlines(), 1):
                    if regex.search(line):
                        matches.append(f"{fpath}:{lineno}:{line.rstrip()}")
                        if len(matches) >= max_results:
                            matches.append(f"... truncated at {max_results} results")
                            return ToolResult(id="", content="\n".join(matches))
            except Exception:
                continue

        if not matches:
            return ToolResult(id="", content="No matches found.")
        return ToolResult(id="", content="\n".join(matches))
