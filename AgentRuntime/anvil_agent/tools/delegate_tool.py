"""delegate_task: hand work to a subagent, then list / steer / stop it (modeled on Hermes' delegate_task)."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Callable

from anvil_agent.context import current_agent_id
from anvil_agent.models.types import ToolResult
from anvil_agent.subagents.manager import SubagentError, SubagentManager, SubagentSpec
from anvil_agent.tools.base import Tool

DEFAULT_FOREGROUND_TIMEOUT = 900.0


class DelegateTool(Tool):
    name = "delegate_task"
    description = (
        "Delegate a self-contained task to a subagent that works independently and reports back. "
        "action='spawn' (default) starts one: foreground waits for the result, background=true returns an id "
        "immediately and the result is attached to a later tool result. While children run: 'list' shows them, "
        "'steer' sends a course correction, 'stop' cancels one, 'wait' blocks for a background child."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["spawn", "list", "steer", "stop", "wait"]},
            "goal": {"type": "string", "description": "What the subagent must accomplish (spawn)."},
            "context": {"type": "string", "description": "Background it needs: paths, constraints, findings so far."},
            "background": {"type": "boolean", "description": "Return immediately instead of waiting."},
            "tools": {"type": "array", "items": {"type": "string"}, "description": "Restrict the subagent to these tool names."},
            "max_iterations": {"type": "integer"},
            "subagent_id": {"type": "string", "description": "Target for steer/stop/wait."},
            "message": {"type": "string", "description": "Course correction text for steer."},
        },
    }

    def __init__(self, manager_getter: Callable[[], SubagentManager | None]) -> None:
        self._manager_getter = manager_getter

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        mgr = self._manager_getter()
        if mgr is None:
            return self._out({"error": "subagents are not available in this session"}, True)
        parent = current_agent_id.get()
        action = arguments.get("action") or "spawn"
        try:
            if action == "list":
                return self._out({"subagents": [r.to_dict() for r in mgr.list(parent_id=parent)]})
            if action == "steer":
                sid = arguments.get("subagent_id", "")
                ok = mgr.steer(sid, arguments.get("message", ""))
                return self._out({"steered": ok, **({} if ok else {"note": "unknown, finished, or empty message"})}, not ok)
            if action == "stop":
                return self._out(await mgr.stop(arguments.get("subagent_id", "")))
            if action == "wait":
                rec = await mgr.wait(arguments.get("subagent_id", ""), DEFAULT_FOREGROUND_TIMEOUT)
                rec.delivered = rec.state.terminal or rec.delivered
                return self._out(rec.to_dict(), rec.state.value == "failed")
            if action != "spawn":
                return self._out({"error": f"unknown action '{action}'"}, True)

            spec = SubagentSpec(
                goal=arguments.get("goal", ""),
                context=arguments.get("context", ""),
                allowed_tools=arguments.get("tools") or None,
                max_iterations=int(arguments.get("max_iterations") or 40),
            )
            rec = await mgr.spawn(spec, parent_id=parent)
            if arguments.get("background"):
                return self._out({"id": rec.id, "state": rec.state.value, "note": "running in background"})
            try:
                rec = await mgr.wait(rec.id, DEFAULT_FOREGROUND_TIMEOUT)
            except asyncio.CancelledError:
                await mgr.stop(rec.id)
                raise
            if not rec.state.terminal:  # foreground timeout: leave it running, hand back the id
                return self._out({"id": rec.id, "state": rec.state.value, "note": "still running; use action='wait'"})
            rec.delivered = True
            return self._out(rec.to_dict(), rec.state.value == "failed")
        except SubagentError as exc:
            return self._out({"error": str(exc)}, True)

    @staticmethod
    def _out(payload: dict[str, Any], is_error: bool = False) -> ToolResult:
        return ToolResult(id="", content=json.dumps(payload, indent=1), is_error=is_error)
