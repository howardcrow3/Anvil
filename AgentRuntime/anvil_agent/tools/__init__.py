"""Built-in tools for Anvil agent."""

from __future__ import annotations

from typing import TYPE_CHECKING

from anvil_agent.tools.registry import ToolRegistry
from anvil_agent.tools.base import Tool

if TYPE_CHECKING:
    from anvil_agent.session.search import SessionSearchDB


def create_default_registry(
    search_db: SessionSearchDB | None = None,
) -> ToolRegistry:
    """Create a registry with all built-in tools."""
    from anvil_agent.tools.read_tool import ReadTool
    from anvil_agent.tools.write_tool import WriteTool
    from anvil_agent.tools.edit_tool import EditTool
    from anvil_agent.tools.bash_tool import BashTool
    from anvil_agent.tools.glob_tool import GlobTool
    from anvil_agent.tools.grep_tool import GrepTool
    from anvil_agent.tools.web_search_tool import WebSearchTool
    from anvil_agent.tools.web_fetch_tool import WebFetchTool
    from anvil_agent.tools.ask_user_tool import AskUserTool

    registry = ToolRegistry()
    for tool_cls in [
        ReadTool,
        WriteTool,
        EditTool,
        BashTool,
        GlobTool,
        GrepTool,
        WebSearchTool,
        WebFetchTool,
        AskUserTool,
    ]:
        registry.register(tool_cls())

    # Session search (requires initialized DB)
    if search_db is not None:
        from anvil_agent.tools.session_search_tool import SessionSearchTool
        registry.register(SessionSearchTool(search_db))

    return registry


__all__ = ["Tool", "ToolRegistry", "create_default_registry"]
