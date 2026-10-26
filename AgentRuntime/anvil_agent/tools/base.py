"""Abstract base class for tools."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from anvil_agent.models.types import ToolResult


class Tool(ABC):
    """Base class for all agent tools."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema
    requires_approval: bool = False
    # Rarely used tools can be hidden behind tool_search/tool_describe/tool_call to keep the
    # per-request tool schema small. See anvil_agent/tools/tool_search.py.
    defer: bool = False

    @abstractmethod
    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        """Execute the tool with the given arguments."""
        ...

    def to_schema(self) -> dict[str, Any]:
        """Return the tool definition for sending to the model."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


def resolve_path(arguments: dict[str, Any], key: str = "file_path", default: str | None = None) -> Path:
    """A path argument, resolved against the injected ``working_dir`` when it is relative.

    The runtime process's own cwd is the runtime install directory (not the user's project), so a
    relative path must never be resolved against it.
    """
    raw = arguments.get(key) or default
    if raw is None:
        raise KeyError(key)
    path = Path(raw)
    base = arguments.get("working_dir")
    if base and not path.is_absolute():
        path = Path(base) / path
    return path
