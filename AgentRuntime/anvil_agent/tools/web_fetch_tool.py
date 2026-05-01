"""Web fetch tool."""

from __future__ import annotations

import re
from typing import Any

import httpx

from anvil_agent.models.types import ToolResult
from anvil_agent.tools.base import Tool


class WebFetchTool(Tool):
    name = "web_fetch"
    description = "Fetch a web page and return its text content."
    requires_approval = False
    parameters = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL to fetch.",
            },
        },
        "required": ["url"],
    }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        url = arguments["url"]

        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                content_type = resp.headers.get("content-type", "")

                if "html" in content_type:
                    text = self._strip_html(resp.text)
                else:
                    text = resp.text

                if len(text) > 50000:
                    text = text[:50000] + "\n... (truncated)"

                return ToolResult(id="", content=text)
        except Exception as e:
            return ToolResult(id="", content=f"Error fetching URL: {e}", is_error=True)

    def _strip_html(self, html: str) -> str:
        """Basic HTML to text conversion."""
        text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()
