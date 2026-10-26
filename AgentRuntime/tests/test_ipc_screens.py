"""The RPC methods behind the Projects, Kanban, Teams, Skills and Endpoints screens, against a real runtime process."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
from pathlib import Path

import aiohttp
import pytest

TOKEN = "screens-test-token"
ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def runtime(tmp_path_factory):
    home = tmp_path_factory.mktemp("home")
    project = home / "project"
    project.mkdir()
    env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home), "ANVIL_WS_TOKEN": TOKEN}
    proc = subprocess.Popen(
        [sys.executable, "-u", "-m", "anvil_agent", "--no-socket", "--ws-port", "0", "--exit-on-stdin-eof",
         "--project-dir", str(project), "--log-level", "WARNING"],
        cwd=ROOT, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    port: list[int] = []
    ready = threading.Event()

    def pump() -> None:
        assert proc.stdout
        for line in proc.stdout:
            m = re.search(r"WS_READY:(\{.*\})", line)
            if m and not port:
                port.append(json.loads(m.group(1))["port"])
                ready.set()

    threading.Thread(target=pump, daemon=True).start()
    if not ready.wait(40):
        proc.kill()
        pytest.fail("runtime did not report WS_READY")
    yield {"port": port[0], "home": home}
    proc.stdin.close()  # EOF is the shutdown signal
    try:
        proc.wait(10)
    except subprocess.TimeoutExpired:
        proc.kill()


class Client:
    def __init__(self, ws):
        self.ws, self.n = ws, 0

    async def call(self, method, **params):
        self.n += 1
        await self.ws.send_json({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params})
        while True:
            msg = await self.ws.receive_json(timeout=20)
            if msg.get("id") == self.n:
                assert msg.get("error") is None, msg
                return msg["result"]


@pytest.fixture
async def client(runtime):
    async with aiohttp.ClientSession() as http, http.ws_connect(
        f"http://127.0.0.1:{runtime['port']}/rpc?token={TOKEN}"
    ) as ws:
        yield Client(ws)


async def test_projects_crud_and_task_lifecycle(client):
    p = await client.call("project.create", name="Launch", folder_path="/tmp/x", github_repo="o/r")
    assert p["name"] == "Launch" and p["tasks"] == []
    t = await client.call("project.task.create", project_id=p["id"], title="Ship it")
    assert t["status"] == "not_started"
    assert (await client.call("project.task.update", project_id=p["id"], task_id=t["id"], status="completed"))["status"] == "ok"
    got = await client.call("project.get", id=p["id"])
    assert got["tasks"][0]["status"] == "completed"
    assert "error" in await client.call("project.task.update", project_id=p["id"], task_id="nope", status="completed")
    assert (await client.call("project.task.delete", project_id=p["id"], task_id=t["id"]))["status"] == "ok"
    assert (await client.call("project.get", id=p["id"]))["tasks"] == []
    assert (await client.call("project.delete", id=p["id"]))["status"] == "ok"
    assert p["id"] not in [x["id"] for x in await client.call("project.list")]
    assert "error" in await client.call("project.create", name="")


async def test_kanban_create_block_unblock_complete(client):
    created = (await client.call("kanban.create", title="Write docs", body="b", priority=3))["task"]
    assert created["status"] == "ready" and created["priority"] == 3
    assert (await client.call("kanban.action", id=created["id"], action="block", reason="waiting"))["task"]["status"] == "blocked"
    assert (await client.call("kanban.action", id=created["id"], action="unblock"))["task"]["status"] == "ready"
    done = (await client.call("kanban.action", id=created["id"], action="complete", summary="ok"))["task"]
    assert done["status"] == "done"
    board = await client.call("kanban.list")
    assert any(t["id"] == created["id"] for t in board["tasks"]) and "dispatcher" in board
    assert "error" in await client.call("kanban.action", id=created["id"], action="explode")
    assert "error" in await client.call("kanban.create", title="   ")


async def test_kanban_dependencies_start_in_todo(client):
    parent = (await client.call("kanban.create", title="parent"))["task"]
    child = (await client.call("kanban.create", title="child", parents=[parent["id"]]))["task"]
    assert child["status"] == "todo"
    await client.call("kanban.action", id=parent["id"], action="complete", summary="done")
    shown = (await client.call("kanban.show", id=child["id"]))["task"]
    assert shown["status"] == "ready"


async def test_teams_list_and_shared_tasks(client):
    team = await client.call("team.create", name="Docs crew", members=[{"name": "writer", "role": "drafts"}])
    team_id = team["team_id"]
    teams = await client.call("team.list")
    mine = next(t for t in teams if t["id"] == team_id)
    assert mine["name"] == "Docs crew" and mine["members"] == [{"name": "writer", "role": "drafts"}]
    await client.call("team.task.create", team_id=team_id, title="Outline")
    tasks = await client.call("team.task.list", team_id=team_id)
    assert [t["title"] for t in tasks] == ["Outline"] and tasks[0]["status"] == "pending"


async def test_skills_import_toggle_delete(client):
    content = "---\nname: release-notes\ndescription: writes release notes\n---\nSummarize commits."
    assert (await client.call("skills.import", name="Release Notes", content=content))["name"] == "release-notes"
    item = next(s for s in await client.call("skills.list") if s["id"] == "release-notes")
    assert item["enabled"] and item["type"] == "skill"
    await client.call("skills.toggle", id="release-notes", enabled=False)
    assert not next(s for s in await client.call("skills.list") if s["id"] == "release-notes")["enabled"]
    assert (await client.call("skills.delete", id="release-notes"))["status"] == "ok"
    assert all(s["id"] != "release-notes" for s in await client.call("skills.list"))
    assert "error" in await client.call("skills.import", name="", content="x")
    assert "error" in await client.call("skills.delete", id="does-not-exist")


async def test_saving_endpoints_registers_models_immediately(client, runtime):
    before = {m["id"] for m in await client.call("model.list")}
    assert "custom:lm" not in before
    endpoints = [{"name": "lm", "base_url": "http://127.0.0.1:9/v1", "api_key": "", "default_model": "qwen"}]
    assert (await client.call("settings.set", key="endpoints", value=endpoints))["status"] == "ok"
    models = {m["id"]: m for m in await client.call("model.list")}
    assert models["custom:lm"]["provider"] == "custom" and models["custom:lm"]["status"] == "available"
    saved = json.loads((runtime["home"] / ".anvil" / "config.json").read_text())
    assert saved["endpoints"] == endpoints  # persisted for the next launch
