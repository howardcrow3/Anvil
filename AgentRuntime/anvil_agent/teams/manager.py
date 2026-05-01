"""Team management - coordinates multiple agent processes."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

TEAMS_DIR = Path.home() / ".anvil" / "teams"
TASKS_DIR = Path.home() / ".anvil" / "tasks"


class TeamManager:
    """Manages agent teams with shared task lists and messaging."""

    def __init__(self) -> None:
        self._teams_dir = TEAMS_DIR
        self._tasks_dir = TASKS_DIR
        self._teams_dir.mkdir(parents=True, exist_ok=True)
        self._tasks_dir.mkdir(parents=True, exist_ok=True)
        self._processes: dict[str, asyncio.subprocess.Process] = {}

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
        logger.info("Spawned teammate %s (pid=%s)", member_id, proc.pid)
        return member_id

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

    def create_task(self, team_id: str, title: str, description: str = "") -> str:
        """Create a shared task for the team."""
        task_id = str(uuid.uuid4())
        task = {
            "id": task_id,
            "team_id": team_id,
            "title": title,
            "description": description,
            "status": "pending",
            "assigned_to": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        path = self._tasks_dir / f"{task_id}.json"
        path.write_text(json.dumps(task, indent=2))
        return task_id

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
        self._processes.clear()
