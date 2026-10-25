"""Per-task execution context shared by the agent loop and tools."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

# Id of the agent whose loop is running in this asyncio task ("main" for the user's session).
current_agent_id: ContextVar[str] = ContextVar("anvil_agent_id", default="main")
# Free-form launch environment for a subagent (e.g. {"kanban_task": "t_ab12", "unattended": True}).
current_agent_env: ContextVar[dict[str, Any]] = ContextVar("anvil_agent_env", default={})
