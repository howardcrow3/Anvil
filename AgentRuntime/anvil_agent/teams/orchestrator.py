"""Team orchestrator - coordinates multi-model agent teams."""

from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path
from typing import Any

from anvil_agent.teams.manager import TeamManager

logger = logging.getLogger(__name__)

TEAM_SESSIONS_DIR = Path.home() / ".anvil" / "teams"


class TeamOrchestrator:
    """High-level orchestration for multi-model agent teams.

    Handles team creation from specs, auto-task assignment,
    and teammate lifecycle coordination.
    """

    def __init__(
        self,
        team_manager: TeamManager,
        project_dir: Path | None = None,
    ) -> None:
        self._manager = team_manager
        self._project_dir = project_dir or Path.cwd()

    async def create_team_from_spec(self, spec: dict[str, Any]) -> str:
        """Create a team from a specification dict.

        spec = {
            "name": "Feature Team",
            "lead": {"model": "claude-opus-4-6", "provider": "claude"},
            "teammates": [
                {"name": "coder", "role": "implementation", "model": "mistral-small:24b", "provider": "ollama"},
                {"name": "reviewer", "role": "code_review", "model": "claude-sonnet-4-6", "provider": "claude"},
            ],
            "tasks": [
                {"title": "Implement feature X", "assignee": "coder"},
                {"title": "Review code", "assignee": "reviewer", "depends_on": [0]},
            ]
        }

        Returns the team_id.
        """
        name = spec.get("name", "Team")
        members = spec.get("teammates", [])

        # Create the team
        team_id = await self._manager.create_team(name, members)
        logger.info("Created team %s (%s) with %d members", name, team_id, len(members))

        # Spawn teammate processes
        spawned: dict[str, str] = {}  # name -> member_id
        for member in members:
            member_name = member.get("name", f"agent-{len(spawned)}")
            role = member.get("role", "general")
            model = member.get("model", "claude-sonnet-4-6")
            provider = member.get("provider", "claude")
            socket_path = f"/tmp/anvil_teammate_{uuid.uuid4().hex[:8]}.sock"

            try:
                member_id = await self._manager.spawn_teammate(
                    team_id,
                    role=role,
                    name=member_name,
                    socket_path=socket_path,
                    project_dir=str(self._project_dir),
                    model=model,
                    provider=provider,
                )
                spawned[member_name] = member_id
                logger.info("Spawned teammate %s as %s on %s", member_name, role, model)
            except Exception as exc:
                logger.error("Failed to spawn teammate %s: %s", member_name, exc)

        # Create tasks with dependencies
        task_ids: list[str] = []
        for task_spec in spec.get("tasks", []):
            title = task_spec.get("title", "Untitled")
            description = task_spec.get("description", "")
            assignee = task_spec.get("assignee")

            # Resolve dependency indices to task IDs
            dep_indices = task_spec.get("depends_on", [])
            depends_on: list[str] = []
            for idx in dep_indices:
                if isinstance(idx, int) and 0 <= idx < len(task_ids):
                    depends_on.append(task_ids[idx])
                elif isinstance(idx, str):
                    depends_on.append(idx)

            task_id = self._manager.create_task(
                team_id,
                title=title,
                description=description,
                depends_on=depends_on,
            )
            task_ids.append(task_id)

            # Auto-assign if specified
            if assignee and assignee in spawned:
                self._manager.assign_task(task_id, spawned[assignee])

        return team_id

    async def auto_assign_tasks(self, team_id: str) -> list[dict[str, Any]]:
        """Auto-assign available tasks to idle teammates.

        Returns list of assignments made: [{"task_id": ..., "member_id": ...}]
        """
        available = self._manager.get_available_tasks(team_id)
        teammates = self._manager.list_teammates(team_id)
        idle = [t for t in teammates if t.get("state") == "idle"]

        assignments: list[dict[str, Any]] = []
        for task, teammate in zip(available, idle):
            task_id = task["id"]
            member_id = teammate["id"]
            self._manager.assign_task(task_id, member_id)
            self._manager.set_teammate_state(member_id, "working", current_task=task_id)
            assignments.append({"task_id": task_id, "member_id": member_id})
            logger.info("Auto-assigned task %s to %s", task["title"], teammate.get("name", member_id))

        return assignments

    async def handle_task_completion(
        self, team_id: str, member_id: str, task_id: str
    ) -> dict[str, Any]:
        """Handle a teammate completing a task.

        Marks task complete, sets teammate idle, triggers auto-assignment
        of newly unblocked tasks.

        Returns summary: {"completed": task_id, "unblocked": [...], "new_assignments": [...]}
        """
        # Mark task as completed
        unblocked = self._manager.complete_task(task_id)
        logger.info("Task %s completed by %s, unblocked %d tasks", task_id, member_id, len(unblocked))

        # Set teammate back to idle
        self._manager.set_teammate_state(member_id, "idle", current_task=None)

        # Auto-assign newly available tasks
        new_assignments = await self.auto_assign_tasks(team_id)

        # Check if all tasks are done
        all_tasks = self._manager.list_tasks(team_id)
        all_done = all(t["status"] == "completed" for t in all_tasks) if all_tasks else False

        return {
            "completed": task_id,
            "unblocked": unblocked,
            "new_assignments": new_assignments,
            "team_complete": all_done,
        }

    def get_team_progress(self, team_id: str) -> dict[str, Any]:
        """Get a summary of team progress."""
        tasks = self._manager.list_tasks(team_id)
        teammates = self._manager.list_teammates(team_id)

        total = len(tasks)
        completed = sum(1 for t in tasks if t["status"] == "completed")
        in_progress = sum(1 for t in tasks if t["status"] == "in_progress")
        pending = sum(1 for t in tasks if t["status"] == "pending")
        blocked = len(self._manager.get_blocked_tasks(team_id))

        active_teammates = sum(1 for t in teammates if t.get("state") == "working")
        idle_teammates = sum(1 for t in teammates if t.get("state") == "idle")

        return {
            "tasks": {
                "total": total,
                "completed": completed,
                "in_progress": in_progress,
                "pending": pending,
                "blocked": blocked,
            },
            "teammates": {
                "total": len(teammates),
                "active": active_teammates,
                "idle": idle_teammates,
            },
            "progress_pct": round(completed / total * 100, 1) if total > 0 else 0,
        }

    async def send_task_to_teammate(
        self, team_id: str, member_id: str, task_id: str
    ) -> None:
        """Send a task assignment message to a teammate via mailbox."""
        tasks = self._manager.list_tasks(team_id)
        task = next((t for t in tasks if t["id"] == task_id), None)
        if not task:
            return

        content = (
            f"You have been assigned a task:\n"
            f"Title: {task['title']}\n"
            f"Description: {task.get('description', 'No description')}\n\n"
            f"Please work on this task and report back when done."
        )
        self._manager.send_message(
            team_id,
            from_agent="lead",
            to_agent=member_id,
            content=content,
        )
