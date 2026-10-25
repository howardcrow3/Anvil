"""The ``kanban`` tool: one narrow tool with an action enum (create, list, show, link, comment, complete, block, unblock, archive)."""

from __future__ import annotations

import json
from typing import Any, Callable

from anvil_agent.context import current_agent_env, current_agent_id
from anvil_agent.kanban.db import KanbanDB, KanbanError
from anvil_agent.models.types import ToolResult
from anvil_agent.tools.base import Tool


class KanbanTool(Tool):
    name = "kanban"
    defer = True
    description = (
        "Manage the durable task board shared by you, your subagents and the user. Tasks can depend on "
        "parent tasks and become ready automatically when their parents are done. Actions: create "
        "(title, body, parents, assignee, priority), list (status), show, link (parent_id, task_id), "
        "comment, complete (summary), block (reason), unblock, archive. Inside a kanban worker, task_id "
        "defaults to the worker's own task."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["create", "list", "show", "link", "comment", "complete", "block", "unblock", "archive"]},
            "task_id": {"type": "string"},
            "title": {"type": "string"},
            "body": {"type": "string", "description": "Task description, or comment text for action=comment."},
            "parents": {"type": "array", "items": {"type": "string"}, "description": "Task ids this task depends on."},
            "parent_id": {"type": "string"},
            "assignee": {"type": "string"},
            "priority": {"type": "integer"},
            "status": {"type": "string", "enum": ["todo", "ready", "running", "blocked", "done"]},
            "summary": {"type": "string"},
            "reason": {"type": "string"},
        },
        "required": ["action"],
    }

    def __init__(self, db_getter: Callable[[], KanbanDB | None]) -> None:
        self._db_getter = db_getter

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        db = self._db_getter()
        if db is None:
            return self._out({"error": "kanban is not available"}, True)
        env = current_agent_env.get()
        who = current_agent_id.get()
        action = arguments.get("action")
        tid = arguments.get("task_id") or env.get("kanban_task")
        try:
            if action == "create":
                t = db.create_task(
                    arguments.get("title", ""), arguments.get("body", ""),
                    assignee=arguments.get("assignee"), priority=int(arguments.get("priority") or 0),
                    parents=arguments.get("parents") or [], created_by=who,
                )
                return self._out(self._brief(t))
            if action == "list":
                return self._out({"tasks": [self._brief(t) for t in db.list_tasks(arguments.get("status"))]})
            if action == "link":
                db.link(arguments.get("parent_id", ""), tid or "")
                return self._out({"linked": True})
            if not tid:
                return self._out({"error": "task_id is required"}, True)
            if action == "show":
                return self._out(db.get_task(tid))
            if action == "comment":
                db.comment(tid, who, arguments.get("body", ""))
                return self._out({"ok": True})
            if action == "complete":
                t = db.complete(tid, arguments.get("summary", ""), force=not env.get("kanban_task"), by=who)
                return self._out({**self._brief(t), "promoted": t.get("promoted", [])})
            if action == "block":
                return self._out(self._brief(db.block(tid, arguments.get("reason", ""), by=who)))
            if action == "unblock":
                return self._out(self._brief(db.unblock(tid)))
            if action == "archive":
                db.archive(tid)
                return self._out({"archived": tid})
            return self._out({"error": f"unknown action '{action}'"}, True)
        except KanbanError as exc:
            return self._out({"error": str(exc)}, True)

    @staticmethod
    def _brief(t: dict[str, Any]) -> dict[str, Any]:
        return {k: t.get(k) for k in ("id", "title", "status", "assignee", "priority", "parents", "result") if k in t}

    @staticmethod
    def _out(payload: dict[str, Any], is_error: bool = False) -> ToolResult:
        return ToolResult(id="", content=json.dumps(payload, indent=1, default=str), is_error=is_error)
