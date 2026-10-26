"""Regression tests for issues found in the whole-codebase code review (tools, hooks, planning, sessions)."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

import pytest

from anvil_agent.agent_loop import AgentLoop
from anvil_agent.hooks.engine import HookEvent, HooksEngine
from anvil_agent.models.router import ModelProvider, ModelRouter
from anvil_agent.models.types import ChatChunk, ToolCallDelta, ToolCallRequest, ToolResult
from anvil_agent.session.manager import SessionManager
from anvil_agent.tools import create_default_registry
from anvil_agent.tools.bash_tool import STREAM_LIMIT, BashTool
from anvil_agent.tools.base import Tool, resolve_path
from anvil_agent.tools.edit_tool import EditTool
from anvil_agent.tools.glob_tool import GlobTool
from anvil_agent.tools.grep_tool import GrepTool
from anvil_agent.tools.read_tool import ReadTool
from anvil_agent.tools.registry import ToolRegistry
from anvil_agent.tools.web_fetch_tool import WebFetchTool, check_public_url
from anvil_agent.tools.write_tool import WriteTool

posix_only = pytest.mark.skipif(os.name != "posix", reason="process groups / sh")


# ── bash ────────────────────────────────────────────────────────────────────


@posix_only
async def test_bash_timeout_kills_the_whole_process_tree(tmp_path):
    marker = tmp_path / "alive"
    # A grandchild that would keep touching the marker if it survived the timeout.
    cmd = f"(while true; do date +%s%N > {marker}; sleep 0.1; done) & wait"
    res = await BashTool().execute({"command": cmd, "timeout": 1})
    assert res.is_error and "timed out" in res.content
    await asyncio.sleep(0.3)
    before = marker.read_text()
    await asyncio.sleep(0.5)
    assert marker.read_text() == before, "grandchild kept running after the timeout"


async def test_bash_reports_exit_code_first_and_flags_failure():
    res = await BashTool().execute({"command": "echo out; echo err >&2; exit 3"})
    assert res.is_error
    assert res.content.splitlines()[0] == "Exit code: 3"
    assert "out" in res.content and "STDERR:\nerr" in res.content


@posix_only
async def test_bash_noisy_stdout_cannot_push_stderr_or_exit_code_out():
    res = await BashTool().execute({"command": "yes x | head -c 200000; echo FAILED >&2; exit 1"})
    assert res.content.startswith("Exit code: 1")
    assert "FAILED" in res.content
    assert len(res.content) < 3 * STREAM_LIMIT
    assert "characters omitted" in res.content


# ── file tools ──────────────────────────────────────────────────────────────


def test_resolve_path_uses_working_dir_for_relative_paths_only(tmp_path):
    assert resolve_path({"file_path": "a/b.txt", "working_dir": str(tmp_path)}) == tmp_path / "a" / "b.txt"
    abs_path = tmp_path / "x.txt"
    assert resolve_path({"file_path": str(abs_path), "working_dir": "/elsewhere"}) == abs_path
    assert resolve_path({"file_path": "rel.txt"}) == Path("rel.txt")
    with pytest.raises(KeyError):
        resolve_path({})


async def test_file_tools_resolve_relative_paths_against_working_dir(tmp_path):
    wd = str(tmp_path)
    w = await WriteTool().execute({"file_path": "sub/new.txt", "content": "hello\nworld\n", "working_dir": wd})
    assert not w.is_error and (tmp_path / "sub" / "new.txt").read_text() == "hello\nworld\n"

    r = await ReadTool().execute({"file_path": "sub/new.txt", "working_dir": wd})
    assert not r.is_error and "hello" in r.content

    e = await EditTool().execute({"file_path": "sub/new.txt", "old_string": "world", "new_string": "there", "working_dir": wd})
    assert not e.is_error and "there" in (tmp_path / "sub" / "new.txt").read_text()

    g = await GlobTool().execute({"pattern": "**/*.txt", "working_dir": wd})
    assert "new.txt" in g.content

    gr = await GrepTool().execute({"pattern": "there", "path": "sub", "working_dir": wd})
    assert "new.txt" in gr.content or "there" in gr.content


async def test_edit_preserves_crlf_line_endings(tmp_path):
    p = tmp_path / "win.txt"
    p.write_bytes(b"one\r\ntwo\r\nthree\r\n")
    res = await EditTool().execute({"file_path": str(p), "old_string": "two\nthree", "new_string": "2\n3"})
    assert not res.is_error, res.content
    assert p.read_bytes() == b"one\r\n2\r\n3\r\n"


async def test_edit_preserves_lf_files(tmp_path):
    p = tmp_path / "unix.txt"
    p.write_bytes(b"a\nb\n")
    res = await EditTool().execute({"file_path": str(p), "old_string": "b", "new_string": "c"})
    assert not res.is_error and p.read_bytes() == b"a\nc\n"


# ── web_fetch ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",
        "http://localhost:8080/",
        "http://127.0.0.1/",
        "http://[::1]/",
        "http://10.0.0.1/",
        "http://192.168.1.1/",
        "http://0x7f.1/",
        "http://2130706433/",
        "file:///etc/passwd",
        "ftp://example.com/",
        "not a url",
    ],
)
async def test_check_public_url_refuses_internal_and_non_http(url):
    assert await check_public_url(url)


async def test_check_public_url_allows_public_literal():
    assert await check_public_url("https://93.184.216.34/") is None


async def test_web_fetch_requires_url():
    res = await WebFetchTool().execute({})
    assert res.is_error and "url" in res.content


async def test_web_fetch_rechecks_every_redirect_hop(monkeypatch):
    """A public URL that redirects to the metadata service must be refused at the second hop."""
    import httpx
    from anvil_agent.tools import web_fetch_tool as wf

    seen: list[str] = []

    async def fake_check(url: str):
        seen.append(url)
        return "non-public" if "169.254" in url else None

    class FakeClient:
        def __init__(self, *a, **k): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url):
            return httpx.Response(302, headers={"location": "http://169.254.169.254/x"}, request=httpx.Request("GET", url))

    monkeypatch.setattr(wf, "check_public_url", fake_check)
    monkeypatch.setattr(wf.httpx, "AsyncClient", FakeClient)
    res = await WebFetchTool().execute({"url": "http://public.example/"})
    assert res.is_error and "refusing" in res.content
    assert seen == ["http://public.example/", "http://169.254.169.254/x"]


# ── registry ────────────────────────────────────────────────────────────────


class _Deferred(Tool):
    name, description, defer = "later", "A deferred tool.", True
    parameters = {"type": "object", "properties": {}}

    async def execute(self, arguments):
        return ToolResult(id="", content="ok")


async def test_registry_bridge_exception_becomes_error_result(monkeypatch):
    r = ToolRegistry()
    r.register(_Deferred())
    bridge = r._get_bridge()

    async def boom(request):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(bridge, "handle", boom)
    res = await r.execute(ToolCallRequest(id="1", name="tool_search", arguments={"query": "x"}))
    assert res.is_error and "kaboom" in res.content and res.id == "1"


# ── hooks ───────────────────────────────────────────────────────────────────


def _project_with_hook(tmp_path: Path) -> Path:
    hooks = tmp_path / ".claude" / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "h.json").write_text(json.dumps([{"event": "PreToolUse", "type": "command", "command": "exit 2"}]))
    return tmp_path


def test_untrusted_project_hooks_are_ignored(tmp_path, monkeypatch):
    monkeypatch.setattr("anvil_agent.hooks.engine.GLOBAL_HOOKS_PATH", tmp_path / "none.json")
    eng = HooksEngine()
    eng.load_from_files(_project_with_hook(tmp_path / "proj"))
    assert eng._hooks == []


def test_trusted_project_hooks_load(tmp_path, monkeypatch):
    monkeypatch.setattr("anvil_agent.hooks.engine.GLOBAL_HOOKS_PATH", tmp_path / "none.json")
    eng = HooksEngine()
    eng.load_from_files(_project_with_hook(tmp_path / "proj"), trust_project=True)
    assert len(eng._hooks) == 1


@posix_only
@pytest.mark.parametrize("event,blocks", [(HookEvent.PRE_TOOL_USE, True), (HookEvent.USER_PROMPT_SUBMIT, True), (HookEvent.POST_TOOL_USE, False)])
async def test_hook_timeout_fails_closed_only_for_blocking_events(monkeypatch, tmp_path, event, blocks):
    monkeypatch.setattr("anvil_agent.hooks.engine.HOOK_TIMEOUT", 0.3)
    marker = tmp_path / "survivor"
    eng = HooksEngine([{"event": event.value, "type": "command", "command": f"(sleep 1; touch {marker}) & sleep 5"}])
    allowed, out = await eng.run(event, {"tool_name": "bash"})
    assert allowed is (not blocks)
    if blocks:
        assert out and "Blocked" in out
    await asyncio.sleep(1.3)
    assert not marker.exists(), "hook process tree was not killed on timeout"


@posix_only
async def test_command_hook_runs_in_project_dir(tmp_path):
    eng = HooksEngine([{"event": "PreToolUse", "type": "command", "command": "pwd"}])
    eng._project_dir = tmp_path
    allowed, out = await eng.run(HookEvent.PRE_TOOL_USE, {})
    assert allowed and Path(out).resolve() == tmp_path.resolve()


# ── planning mode ───────────────────────────────────────────────────────────


class _OneCall(ModelProvider):
    model_name = "one"

    def __init__(self, tool: str):
        self.tool, self.n = tool, 0

    async def health_check(self):
        return True

    async def chat(self, messages, tools=None, stream=True):
        self.n += 1
        if self.n == 1:
            yield ChatChunk(tool_call_delta=ToolCallDelta(id="c1", name=self.tool))
            yield ChatChunk(tool_call_delta=ToolCallDelta(id="c1", arguments_delta="{}"))
            yield ChatChunk(finish_reason="tool_use")
        else:
            yield ChatChunk(delta_text="done", finish_reason="end_turn")


@pytest.mark.parametrize("tool", ["delegate_task", "skill_manage", "memory", "kanban", "bash", "write_file", "edit_file"])
async def test_planning_mode_blocks_mutating_tools(tool):
    from anvil_agent.models.types import ChatMessage

    reg = ToolRegistry()

    class T(Tool):
        name, description = tool, "x"
        parameters = {"type": "object", "properties": {}}

        async def execute(self, arguments):
            raise AssertionError("must not run in planning mode")

    reg.register(T())
    loop = AgentLoop(_OneCall(tool), reg, planning_mode=True)
    events = [e async for e in loop.run([ChatMessage(role="user", content="go")])]
    results = [e for e in events if e["type"] == "tool_result"]
    assert results and results[0]["is_error"] and "planning mode" in results[0]["content"]


# ── sessions ────────────────────────────────────────────────────────────────


def test_list_sessions_most_recent_first(tmp_path):
    sm = SessionManager(sessions_dir=tmp_path)
    ids = [sm.create(name=f"s{i}", session_id=f"id-{i}") for i in range(3)]
    # Make activity order differ from creation and from name order.
    for sid, stamp in zip(ids, ["2026-01-02T00:00:00+00:00", "2026-03-01T00:00:00+00:00", "2026-02-01T00:00:00+00:00"]):
        p = tmp_path / f"{sid}.meta.json"
        meta = json.loads(p.read_text())
        meta["last_active"] = stamp
        p.write_text(json.dumps(meta))
    assert [s["id"] for s in sm.list_sessions()] == ["id-1", "id-2", "id-0"]


# ── model router ────────────────────────────────────────────────────────────


class _P(ModelProvider):
    model_name = "p"

    async def health_check(self):
        return True

    async def chat(self, messages, tools=None, stream=True):
        yield ChatChunk(delta_text="x")


def test_router_unregister_falls_back_then_empties():
    r = ModelRouter()
    r.register("a", _P())
    r.register("b", _P())
    r.select("a")
    r.unregister("a")
    assert r.active_model_id == "b" and not r.has("a")
    r.unregister("b")
    assert r.active_model_id is None
    r.unregister("missing")  # no error
