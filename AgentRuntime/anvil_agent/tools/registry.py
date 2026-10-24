"""Tool registry for managing available tools."""

from __future__ import annotations

from typing import Any, Iterable

from anvil_agent.models.types import ToolCallRequest, ToolResult
from anvil_agent.tools.base import Tool

BRIDGE_TOOL_NAMES = frozenset({"tool_search", "tool_describe", "tool_call"})


class ToolRegistry:
    """Registry that holds and manages all available tools.

    Tools with ``defer = True`` are hidden from the model-visible schema list and reached through
    the tool_search / tool_describe / tool_call bridge (progressive disclosure, after Hermes Agent).
    ``tool_search`` is "auto"/"on" (defer when any tool is deferrable) or "off" (everything eager).
    """

    def __init__(self, tool_search: str = "auto") -> None:
        self._tools: dict[str, Tool] = {}
        self._deferred: set[str] = set()
        self.tool_search = tool_search
        self._bridge: Any = None

    # -- registration ---------------------------------------------------------

    def register(self, tool: Tool) -> None:
        if tool.name in BRIDGE_TOOL_NAMES:
            raise ValueError(f"'{tool.name}' is a reserved tool-search bridge name")
        self._tools[tool.name] = tool
        if getattr(tool, "defer", False):
            self._deferred.add(tool.name)
        else:
            self._deferred.discard(tool.name)

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)
        self._deferred.discard(name)

    def defer(self, *names: str) -> None:
        self._deferred.update(n for n in names if n in self._tools)

    def undefer(self, *names: str) -> None:
        self._deferred.difference_update(names)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def filtered(self, allowed: Iterable[str] | None = None, blocked: Iterable[str] = ()) -> "ToolRegistry":
        """A new registry sharing tool objects, restricted to ``allowed`` and minus ``blocked``."""
        allow = set(allowed) if allowed is not None else None
        block = set(blocked)
        out = ToolRegistry(self.tool_search)
        for name, tool in self._tools.items():
            if name in block or (allow is not None and name not in allow):
                continue
            out._tools[name] = tool
            if name in self._deferred:
                out._deferred.add(name)
        return out

    # -- schemas --------------------------------------------------------------

    @property
    def search_active(self) -> bool:
        return self.tool_search != "off" and bool(self._deferred & self._tools.keys())

    @property
    def deferred_names(self) -> list[str]:
        return sorted(self._deferred & self._tools.keys())

    def _get_bridge(self) -> Any:
        if self._bridge is None:
            from anvil_agent.tools.tool_search import ToolSearchBridge

            self._bridge = ToolSearchBridge(self)
        return self._bridge

    def get_all_schemas(self) -> list[dict[str, Any]]:
        """Model-visible tool definitions (deferred tools replaced by the bridge when active)."""
        if not self.search_active:
            return [tool.to_schema() for tool in self._tools.values()]
        visible = [t.to_schema() for n, t in self._tools.items() if n not in self._deferred]
        return visible + self._get_bridge().schemas()

    # -- execution ------------------------------------------------------------

    def unwrap(self, request: ToolCallRequest) -> tuple[str, dict[str, Any]]:
        """The (name, arguments) a call really targets: ``tool_call`` unwraps to the inner tool, so
        permission, planning and loop-guard checks see the real tool. The arguments dict is shared
        with the request, so callers may inject into it."""
        if request.name == "tool_call" and self.search_active:
            inner = request.arguments.get("name")
            args = request.arguments.get("arguments")
            if isinstance(inner, str) and isinstance(args, dict):
                return inner, args
        return request.name, request.arguments

    async def execute(self, request: ToolCallRequest) -> ToolResult:
        """Execute a tool by name with the given arguments."""
        if request.name in BRIDGE_TOOL_NAMES and self.search_active:
            return await self._get_bridge().handle(request)
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
