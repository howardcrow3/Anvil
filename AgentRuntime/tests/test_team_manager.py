"""Tests for the team manager (task list, messaging, teammate metadata)."""

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from anvil_agent.teams.manager import TeamManager, TeammateState


@pytest.fixture
def tmp_dirs(tmp_path: Path):
    teams = tmp_path / "teams"
    tasks = tmp_path / "tasks"
    teams.mkdir()
    tasks.mkdir()
    return teams, tasks


@pytest.fixture
def manager(tmp_dirs):
    teams_dir, tasks_dir = tmp_dirs
    mgr = TeamManager()
    mgr._teams_dir = teams_dir
    mgr._tasks_dir = tasks_dir
    return mgr


class TestTeamCreation:
    @pytest.mark.asyncio
    async def test_create_team(self, manager: TeamManager):
        team_id = await manager.create_team("Test Team", [{"name": "agent1"}])
        assert team_id
        path = manager._teams_dir / f"{team_id}.json"
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["name"] == "Test Team"
        assert data["status"] == "active"

    @pytest.mark.asyncio
    async def test_get_status(self, manager: TeamManager):
        team_id = await manager.create_team("Status Team", [])
        status = await manager.get_status(team_id)
        assert status["name"] == "Status Team"
        assert "active_processes" in status

    @pytest.mark.asyncio
    async def test_get_status_not_found(self, manager: TeamManager):
        result = await manager.get_status("nonexistent")
        assert "error" in result


class TestTaskManagement:
    @pytest.mark.asyncio
    async def test_create_and_list_tasks(self, manager: TeamManager):
        team_id = await manager.create_team("Task Team", [])
        t1 = manager.create_task(team_id, "Task 1")
        t2 = manager.create_task(team_id, "Task 2")
        tasks = manager.list_tasks(team_id)
        assert len(tasks) == 2
        titles = {t["title"] for t in tasks}
        assert titles == {"Task 1", "Task 2"}

    @pytest.mark.asyncio
    async def test_update_task(self, manager: TeamManager):
        team_id = await manager.create_team("T", [])
        task_id = manager.create_task(team_id, "Update Me")
        updated = manager.update_task(task_id, status="completed")
        assert updated is not None
        assert updated["status"] == "completed"

    @pytest.mark.asyncio
    async def test_update_nonexistent_task(self, manager: TeamManager):
        result = manager.update_task("nonexistent", status="completed")
        assert result is None

    @pytest.mark.asyncio
    async def test_complete_task_returns_unblocked(self, manager: TeamManager):
        team_id = await manager.create_team("Dep Team", [])
        t1 = manager.create_task(team_id, "First")
        t2 = manager.create_task(team_id, "Second", depends_on=[t1])
        t3 = manager.create_task(team_id, "Third", depends_on=[t1])

        unblocked = manager.complete_task(t1)
        assert t2 in unblocked
        assert t3 in unblocked

    @pytest.mark.asyncio
    async def test_get_available_tasks(self, manager: TeamManager):
        team_id = await manager.create_team("Avail Team", [])
        t1 = manager.create_task(team_id, "No deps")
        t2 = manager.create_task(team_id, "Has dep", depends_on=[t1])

        available = manager.get_available_tasks(team_id)
        ids = [t["id"] for t in available]
        assert t1 in ids
        assert t2 not in ids

    @pytest.mark.asyncio
    async def test_get_blocked_tasks(self, manager: TeamManager):
        team_id = await manager.create_team("Block Team", [])
        t1 = manager.create_task(team_id, "First")
        t2 = manager.create_task(team_id, "Blocked", depends_on=[t1])

        blocked = manager.get_blocked_tasks(team_id)
        ids = [t["id"] for t in blocked]
        assert t2 in ids
        assert t1 not in ids

    @pytest.mark.asyncio
    async def test_assign_task(self, manager: TeamManager):
        team_id = await manager.create_team("Assign Team", [])
        task_id = manager.create_task(team_id, "Assign me")
        result = manager.assign_task(task_id, "agent-1")
        assert result is not None
        assert result["assigned_to"] == "agent-1"

    @pytest.mark.asyncio
    async def test_assigned_task_not_available(self, manager: TeamManager):
        team_id = await manager.create_team("AA Team", [])
        task_id = manager.create_task(team_id, "Assigned")
        manager.assign_task(task_id, "someone")
        available = manager.get_available_tasks(team_id)
        assert len(available) == 0


class TestTeammateMetadata:
    def test_set_and_get_teammate_state(self, manager: TeamManager):
        manager._teammate_meta["t1_coder"] = {
            "id": "t1_coder",
            "name": "coder",
            "state": "idle",
            "current_task": None,
        }
        manager.set_teammate_state("t1_coder", "working", current_task="task-1")
        meta = manager.get_teammate("t1_coder")
        assert meta is not None
        assert meta["state"] == "working"
        assert meta["current_task"] == "task-1"

    def test_get_nonexistent_teammate(self, manager: TeamManager):
        assert manager.get_teammate("nope") is None

    def test_list_teammates(self, manager: TeamManager):
        manager._teammate_meta["team1_a"] = {"id": "team1_a", "name": "a", "state": "idle"}
        manager._teammate_meta["team1_b"] = {"id": "team1_b", "name": "b", "state": "working"}
        manager._teammate_meta["team2_c"] = {"id": "team2_c", "name": "c", "state": "idle"}

        mates = manager.list_teammates("team1")
        assert len(mates) == 2
        names = {m["name"] for m in mates}
        assert names == {"a", "b"}


class TestMailbox:
    @pytest.mark.asyncio
    async def test_send_and_read_messages(self, manager: TeamManager):
        team_id = await manager.create_team("Msg Team", [])
        manager.send_message(team_id, "lead", "coder", "Hello!")
        manager.send_message(team_id, "lead", "coder", "Do task 1")
        manager.send_message(team_id, "lead", "reviewer", "Stand by")

        msgs = manager.read_messages(team_id, "coder")
        assert len(msgs) == 2
        contents = {m["content"] for m in msgs}
        assert "Hello!" in contents
        assert "Do task 1" in contents

        # Reading again should return empty (already marked read)
        msgs2 = manager.read_messages(team_id, "coder")
        assert len(msgs2) == 0

    @pytest.mark.asyncio
    async def test_read_messages_empty_mailbox(self, manager: TeamManager):
        team_id = await manager.create_team("Empty Msg", [])
        msgs = manager.read_messages(team_id, "agent")
        assert msgs == []
