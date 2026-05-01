"""Tool registry for managing available tools."""

from __future__ import annotations

from typing import Any

from anvil_agent.models.types import ToolCallRequest, ToolResult
from anvil_agent.tools.base import Tool


class ToolRegistry:
    """Registry that holds and manages all available tools."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def get_all_schemas(self) -> list[dict[str, Any]]:
        """Get JSON Schema definitions for all registered tools."""
        return [tool.to_schema() for tool in self._tools.values()]

    async def execute(self, request: ToolCallRequest) -> ToolResult:
        """Execute a tool by name with the given arguments."""
        tool = self._tools.get(request.name)
        if tool is None:
            return ToolResult(
                id=request.id,
                content=f"Error: Unknown tool '{request.name}'",
                is_error=True,
            )
        try:
            result = await tool.execute(request.arguments)
            result.id = request.id
            return result
        except Exception as e:
            return ToolResult(
                id=request.id,
                content=f"Error executing {request.name}: {e}",
                is_error=True,
            )

    @property
    def tool_names(self) -> list[str]:
        return list(self._tools.keys())
