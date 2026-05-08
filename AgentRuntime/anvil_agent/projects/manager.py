"""Project persistence and management."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PROJECTS_DIR = Path.home() / ".anvil" / "projects"


class ProjectManager:
    """Manages projects stored as JSON files in ~/.anvil/projects/."""

    def __init__(self) -> None:
        self._projects: dict[str, dict[str, Any]] = {}
        self._load_all()

    def _load_all(self) -> None:
        PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
        for f in sorted(PROJECTS_DIR.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                pid = data.get("id", f.stem)
                # Normalize Swift camelCase keys to snake_case
                self._normalize_project(data)
                self._projects[pid] = data
            except Exception as e:
                logger.warning("Failed to load project %s: %s", f.name, e)

    def _normalize_project(self, data: dict[str, Any]) -> None:
        """Normalize Swift camelCase keys to snake_case for consistency."""
        # Project-level keys
        if "folderPath" in data and "folder_path" not in data:
            data["folder_path"] = data.pop("folderPath")
        if "githubRepo" in data and "github_repo" not in data:
            data["github_repo"] = data.pop("githubRepo")
        if "createdAt" in data and "created_at" not in data:
            data["created_at"] = data.pop("createdAt")
        if "updatedAt" in data and "updated_at" not in data:
            data["updated_at"] = data.pop("updatedAt")

        # Task-level keys
        for task in data.get("tasks", []):
            if "sessionId" in task:
                task["session_id"] = task.pop("sessionId")
            if "taskDescription" in task:
                task["description"] = task.pop("taskDescription")
            if "createdAt" in task and "created_at" not in task:
                task["created_at"] = task.pop("createdAt")
            if "updatedAt" in task and "updated_at" not in task:
                task["updated_at"] = task.pop("updatedAt")

    def _save(self, project: dict[str, Any]) -> None:
        PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
        pid = project["id"]
        path = PROJECTS_DIR / f"{pid}.json"
        path.write_text(json.dumps(project, indent=2, default=str), encoding="utf-8")

    def _delete_file(self, pid: str) -> None:
        path = PROJECTS_DIR / f"{pid}.json"
        if path.is_file():
            path.unlink()

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    # ── CRUD ──────────────────────────────────────────────────────

    def create_project(
        self,
        name: str,
        folder_path: str = "",
        github_repo: str = "",
        project_id: str | None = None,
    ) -> dict[str, Any]:
        pid = project_id or str(uuid.uuid4())
        now = self._now_iso()
        project: dict[str, Any] = {
            "id": pid,
            "name": name,
            "folder_path": folder_path,
            "github_repo": github_repo,
            "tasks": [],
            "created_at": now,
            "updated_at": now,
        }
        self._projects[pid] = project
        self._save(project)
        return project

    def list_projects(self) -> list[dict[str, Any]]:
        return sorted(
            self._projects.values(),
            key=lambda p: p.get("updated_at", ""),
            reverse=True,
        )

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        if project_id in self._projects:
            return self._projects[project_id]
        # Try loading from disk (file may have been written by Swift)
        path = PROJECTS_DIR / f"{project_id}.json"
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                self._normalize_project(data)
                self._projects[project_id] = data
                return data
            except Exception:
                pass
        return None

    def delete_project(self, project_id: str) -> bool:
        if project_id in self._projects:
            del self._projects[project_id]
            self._delete_file(project_id)
            return True
        return False

    # ── Tasks ─────────────────────────────────────────────────────

    def add_task(
        self,
        project_id: str,
        title: str,
        description: str = "",
        task_id: str | None = None,
    ) -> dict[str, Any] | None:
        project = self._projects.get(project_id)
        if not project:
            return None
        tid = task_id or str(uuid.uuid4())
        now = self._now_iso()
        task: dict[str, Any] = {
            "id": tid,
            "title": title,
            "description": description,
            "status": "not_started",
            "session_id": None,
            "created_at": now,
            "updated_at": now,
        }
        project.setdefault("tasks", []).append(task)
        project["updated_at"] = now
        self._save(project)
        return task

    def update_task_status(
        self, project_id: str, task_id: str, status: str
    ) -> bool:
        project = self._projects.get(project_id)
        if not project:
            return False
        for task in project.get("tasks", []):
            if task["id"] == task_id:
                task["status"] = status
                task["updated_at"] = self._now_iso()
                project["updated_at"] = task["updated_at"]
                self._save(project)
                return True
        return False

    def delete_task(self, project_id: str, task_id: str) -> bool:
        project = self._projects.get(project_id)
        if not project:
            return False
        before = len(project.get("tasks", []))
        project["tasks"] = [t for t in project.get("tasks", []) if t["id"] != task_id]
        if len(project["tasks"]) < before:
            project["updated_at"] = self._now_iso()
            self._save(project)
            return True
        return False

    def link_session(self, project_id: str, task_id: str, session_id: str) -> bool:
        project = self._projects.get(project_id)
        if not project:
            return False
        for task in project.get("tasks", []):
            if task["id"] == task_id:
                task["session_id"] = session_id
                task["updated_at"] = self._now_iso()
                project["updated_at"] = task["updated_at"]
                self._save(project)
                return True
        return False
