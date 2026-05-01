"""Web search tool using DuckDuckGo."""

from __future__ import annotations

import logging
from typing import Any

from duckduckgo_search import DDGS

from anvil_agent.models.types import ToolResult
from anvil_agent.tools.base import Tool

logger = logging.getLogger(__name__)


class WebSearchTool(Tool):
    name = "web_search"
    description = "Search the web for information using DuckDuckGo."
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
        query = arguments["query"]
        max_results = arguments.get("max_results", 5)

        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=max_results))

            if not results:
                return ToolResult(
                    id="", content="No results found.", is_error=False
                )

            formatted: list[str] = []
            for i, r in enumerate(results, 1):
                formatted.append(
                    f"{i}. **{r.get('title', 'No title')}**\n"
                    f"   URL: {r.get('href', '')}\n"
                    f"   {r.get('body', '')}"
                )

            return ToolResult(
                id="", content="\n\n".join(formatted), is_error=False
            )
        except Exception as e:
            logger.warning("Web search failed: %s", e)
            return ToolResult(
                id="", content=f"Search error: {e}", is_error=True
            )
