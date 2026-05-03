"""Session search tool using FTS5."""

from __future__ import annotations

from typing import Any

from anvil_agent.models.types import ToolResult
from anvil_agent.session.search import SessionSearchDB
from anvil_agent.tools.base import Tool


class SessionSearchTool(Tool):
    name = "session_search"
    description = "Search across past conversation sessions using full-text search."
    requires_approval = False
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query",
            },
            "limit": {
                "type": "integer",
                "description": "Max results",
                "default": 10,
            },
        },
        "required": ["query"],
    }

    def __init__(self, search_db: SessionSearchDB) -> None:
        self._search_db = search_db

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        query = arguments.get("query", "")
        limit = arguments.get("limit", 10)

        if not query:
            return ToolResult(id="", content="Error: No query provided", is_error=True)

        results = await self._search_db.search(query, limit=limit)
        summary = await self._search_db.summarize_results(query, results)
        return ToolResult(id="", content=summary)
