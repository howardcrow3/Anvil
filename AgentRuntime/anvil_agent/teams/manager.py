"""Team management - coordinates multiple agent processes."""

from __future__ import annotations

import asyncio
import json
import logging
import signal
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from anvil_agent.ipc.server import IPCServer

logger = logging.getLogger(__name__)

TEAMS_DIR = Path.home() / ".anvil" / "teams"
TASKS_DIR = Path.home() / ".anvil" / "tasks"


class TeammateState(str, Enum):
    IDLE = "idle"
    WORKING = "working"
    BLOCKED = "blocked"
    STOPPED = "stopped"


class TeamManager:
    """Manages agent teams with shared task lists and messaging."""

    def __init__(self) -> None:
        self._teams_dir = TEAMS_DIR
        self._tasks_dir = TASKS_DIR
        self._teams_dir.mkdir(parents=True, exist_ok=True)
        self._tasks_dir.mkdir(parents=True, exist_ok=True)
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._teammate_meta: dict[str, dict[str, Any]] = {}
        self._ipc_server: IPCServer | None = None

    def set_ipc(self, server: IPCServer) -> None:
        """Set the IPC server for broadcasting events."""
        self._ipc_server = server

    def _fire_and_forget(self, method: str, params: dict[str, Any]) -> None:
        """Broadcast a notification without blocking."""
        if self._ipc_server is None:
            return
        asyncio.create_task(self._ipc_server.broadcast_notification(method, params))

    async def create_team(
        self,
        name: str,
        members: list[dict[str, Any]],
    ) -> str:
        """Create a new agent team and return the team ID."""
        team_id = str(uuid.uuid4())
        team = {
            "id": team_id,
            "name": name,
            "members": members,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "active",
        }
        path = self._teams_dir / f"{team_id}.json"
        path.write_text(json.dumps(team, indent=2))
        return team_id

    async def spawn_teammate(
        self,
        team_id: str,
        role: str,
        socket_path: str,
        project_dir: str,
        name: str = "",
        model: str = "claude-sonnet-4-20250514",
        provider: str = "claude",
    ) -> str:
        """Spawn a new agent process as a teammate."""
        member_id = f"{team_id}_{role}"
        proc = await asyncio.create_subprocess_exec(
            "anvil-agent",
            "--socket-path", socket_path,
            "--project-dir", project_dir,
            "--model", model,
            "--provider", provider,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._processes[member_id] = proc

        # Store teammate metadata
        self._teammate_meta[member_id] = {
            "id": member_id,
            "name": name or role,
            "role": role,
            "model": model,
            "provider": provider,
            "socket_path": socket_path,
            "state": TeammateState.IDLE.value,
            "current_task": None,
            "pid": proc.pid,
        }

        # Wait for "SOCKET:" line from stdout (up to 30s)
        assert proc.stdout is not None
        try:
            while True:
                line_bytes = await asyncio.wait_for(proc.stdout.readline(), timeout=30)
                if not line_bytes:
                    break
                line = line_bytes.decode(errors="replace").strip()
                if line.startswith("SOCKET:"):
                    break
        except asyncio.TimeoutError:
            logger.warning("Timeout waiting for SOCKET line from teammate %s", member_id)

        logger.info("Spawned teammate %s (pid=%s)", member_id, proc.pid)

        self._fire_and_forget("team.teammate_updated", {
            "team_id": team_id,
            "teammate": self._teammate_meta[member_id],
        })

        return member_id

    async def stop_teammate(self, member_id: str) -> None:
        """Stop a teammate process. SIGTERM, then SIGKILL after 5s."""
        proc = self._processes.get(member_id)
        if proc is None or proc.returncode is not None:
            return

        proc.send_signal(signal.SIGTERM)
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()

        logger.info("Stopped teammate %s", member_id)

        if member_id in self._teammate_meta:
            meta = self._teammate_meta[member_id]
            meta["state"] = TeammateState.STOPPED.value
            meta["current_task"] = None
            team_id = member_id.split("_", 1)[0] if "_" in member_id else ""
            self._fire_and_forget("team.teammate_updated", {
                "team_id": team_id,
                "teammate": meta,
            })

    def get_teammate(self, member_id: str) -> dict[str, Any] | None:
        """Return teammate metadata or None."""
        return self._teammate_meta.get(member_id)

    def list_teammates(self, team_id: str) -> list[dict[str, Any]]:
        """Return all teammate metadata for a team."""
        return [
            meta for mid, meta in self._teammate_meta.items()
            if mid.startswith(team_id)
        ]

    def set_teammate_state(
        self,
        member_id: str,
        state: str,
        current_task: str | None = None,
    ) -> None:
        """Update teammate state and optionally current_task."""
        meta = self._teammate_meta.get(member_id)
        if meta is None:
            return
        meta["state"] = state
        meta["current_task"] = current_task
        team_id = member_id.split("_", 1)[0] if "_" in member_id else ""
        self._fire_and_forget("team.teammate_updated", {
            "team_id": team_id,
            "teammate": meta,
        })

    async def get_status(self, team_id: str) -> dict[str, Any]:
        """Get the status of a team."""
        path = self._teams_dir / f"{team_id}.json"
        if not path.exists():
            return {"error": "Team not found"}
        team = json.loads(path.read_text())
        active = {
            k: {"pid": p.pid, "running": p.returncode is None}
            for k, p in self._processes.items()
            if k.startswith(team_id)
        }
        team["active_processes"] = active
        return team

    # Shared task list

    def create_task(
        self,
        team_id: str,
        title: str,
        description: str = "",
        depends_on: list[str] | None = None,
    ) -> str:
        """Create a shared task for the team."""
        task_id = str(uuid.uuid4())
        task = {
            "id": task_id,
            "team_id": team_id,
            "title": title,
            "description": description,
            "status": "pending",
            "assigned_to": None,
            "depends_on": depends_on or [],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        path = self._tasks_dir / f"{task_id}.json"
        path.write_text(json.dumps(task, indent=2))

        self._fire_and_forget("team.task_updated", {
            "team_id": team_id,
            "task": task,
        })

        return task_id

    def _load_task(self, task_id: str) -> dict[str, Any] | None:
        """Load a single task from disk."""
        path = self._tasks_dir / f"{task_id}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except Exception:
            return None

    def _save_task(self, task: dict[str, Any]) -> None:
        """Persist a task to disk."""
        path = self._tasks_dir / f"{task['id']}.json"
        path.write_text(json.dumps(task, indent=2))

    def update_task(self, task_id: str, **kwargs: Any) -> dict[str, Any] | None:
        """Update task fields (status, assigned_to, etc.). Returns updated task or None."""
        task = self._load_task(task_id)
        if task is None:
            return None
        for key, value in kwargs.items():
            if key in task:
                task[key] = value
        self._save_task(task)

        self._fire_and_forget("team.task_updated", {
            "team_id": task.get("team_id", ""),
            "task": task,
        })

        return task

    def get_available_tasks(self, team_id: str) -> list[dict[str, Any]]:
        """Return pending, unassigned tasks whose dependencies are all completed."""
        all_tasks = self.list_tasks(team_id)
        completed_ids = {t["id"] for t in all_tasks if t.get("status") == "completed"}

        available = []
        for task in all_tasks:
            if task.get("status") != "pending":
                continue
            if task.get("assigned_to") is not None:
                continue
            deps = task.get("depends_on", [])
            if all(dep in completed_ids for dep in deps):
                available.append(task)
        return available

    def assign_task(self, task_id: str, member_id: str) -> dict[str, Any] | None:
        """Assign a task to a teammate."""
        return self.update_task(task_id, assigned_to=member_id)

    def complete_task(self, task_id: str) -> list[str]:
        """Mark a task complete and return list of newly unblocked task IDs."""
        task = self.update_task(task_id, status="completed")
        if task is None:
            return []

        team_id = task.get("team_id", "")
        all_tasks = self.list_tasks(team_id)

        # Find completed task IDs (including the one just completed)
        completed_ids = {t["id"] for t in all_tasks if t.get("status") == "completed"}

        # Find tasks that were blocked only by the just-completed task
        newly_unblocked: list[str] = []
        for t in all_tasks:
            if t.get("status") != "pending":
                continue
            deps = t.get("depends_on", [])
            if not deps:
                continue
            if task_id not in deps:
                continue
            # All deps are now satisfied
            if all(dep in completed_ids for dep in deps):
                newly_unblocked.append(t["id"])

        return newly_unblocked

    def get_blocked_tasks(self, team_id: str) -> list[dict[str, Any]]:
        """Return pending tasks that have unsatisfied dependencies."""
        all_tasks = self.list_tasks(team_id)
        completed_ids = {t["id"] for t in all_tasks if t.get("status") == "completed"}
        blocked = []
        for task in all_tasks:
            if task.get("status") != "pending":
                continue
            deps = task.get("depends_on", [])
            if deps and not all(dep in completed_ids for dep in deps):
                blocked.append(task)
        return blocked

    def list_tasks(self, team_id: str) -> list[dict[str, Any]]:
        """List all tasks for a team."""
        tasks = []
        for path in self._tasks_dir.glob("*.json"):
            try:
                task = json.loads(path.read_text())
                if task.get("team_id") == team_id:
                    tasks.append(task)
            except Exception:
                continue
        return sorted(tasks, key=lambda t: t.get("created_at", ""))

    # Mailbox messaging

    def send_message(self, team_id: str, from_agent: str, to_agent: str, content: str) -> None:
        """Send a message between agents via the mailbox."""
        mailbox_dir = self._teams_dir / team_id / "mailbox"
        mailbox_dir.mkdir(parents=True, exist_ok=True)

        msg = {
            "id": str(uuid.uuid4()),
            "from": from_agent,
            "to": to_agent,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "read": False,
        }
        path = mailbox_dir / f"{msg['id']}.json"
        path.write_text(json.dumps(msg, indent=2))

        self._fire_and_forget("team.message", {
            "team_id": team_id,
            "message": msg,
        })

    def read_messages(self, team_id: str, agent_name: str) -> list[dict[str, Any]]:
        """Read unread messages for an agent."""
        mailbox_dir = self._teams_dir / team_id / "mailbox"
        if not mailbox_dir.exists():
            return []

        messages = []
        for path in sorted(mailbox_dir.glob("*.json")):
            try:
                msg = json.loads(path.read_text())
                if msg.get("to") == agent_name and not msg.get("read"):
                    msg["read"] = True
                    path.write_text(json.dumps(msg, indent=2))
                    messages.append(msg)
            except Exception:
                continue
        return messages

    async def stop_all(self) -> None:
        """Terminate all spawned teammate processes."""
        for member_id, proc in self._processes.items():
            if proc.returncode is None:
                proc.terminate()
                logger.info("Terminated teammate %s", member_id)
            if member_id in self._teammate_meta:
                self._teammate_meta[member_id]["state"] = TeammateState.STOPPED.value
        self._processes.clear()
