"""Web search tool (stub)."""

from __future__ import annotations

from typing import Any

from anvil_agent.models.types import ToolResult
from anvil_agent.tools.base import Tool


class WebSearchTool(Tool):
    name = "web_search"
    description = "Search the web for information. Requires API key configuration."
    requires_approval = False
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query.",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return.",
                "default": 5,
            },
        },
        "required": ["query"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(
            id="",
            content="Web search is not configured. Set up a search API key in settings.",
            is_error=True,
        )
