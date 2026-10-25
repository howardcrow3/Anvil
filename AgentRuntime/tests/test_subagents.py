import asyncio

import pytest

from anvil_agent.agent_loop import AgentLoop
from anvil_agent.models.router import ModelProvider
from anvil_agent.models.types import ChatChunk, ToolCallDelta, ToolResult
from anvil_agent.context import current_agent_env
from anvil_agent.subagents import SubagentError, SubagentManager, SubagentSpec, SubagentState
from anvil_agent.tools.delegate_tool import DelegateTool
from anvil_agent.models.types import ToolCallRequest
import json


class SlowTools:
    def __init__(self, delay=0.05):
        self.delay = delay

    def get_all_schemas(self):
        return [{"name": "work"}]

    async def execute(self, tc):
        await asyncio.sleep(self.delay)
        return ToolResult(id=tc.id, content="did work")


class LoopingProvider(ModelProvider):
    """Calls the `work` tool until it has seen `rounds` tool results, then answers."""

    model_name = "loop"
    supports_tool_use = True

    def __init__(self, rounds=3, answer="all done"):
        self.rounds, self.answer, self.seen_user_rows = rounds, answer, []

    async def health_check(self):
        return True

    async def chat(self, messages, tools=None, stream=True):
        tool_rows = sum(1 for m in messages if m.role == "tool")
        self.seen_user_rows = [m.content for m in messages if m.role == "user"]
        if tool_rows < self.rounds and tools:
            yield ChatChunk(tool_call_delta=ToolCallDelta(id=f"t{tool_rows}", name="work"))
            yield ChatChunk(tool_call_delta=ToolCallDelta(id=f"t{tool_rows}", arguments_delta="{}"))
            yield ChatChunk(finish_reason="tool_use")
        else:
            yield ChatChunk(delta_text=self.answer, finish_reason="end_turn")


def _mgr(rounds=3, delay=0.05, **kw):
    prov = LoopingProvider(rounds)
    mgr = SubagentManager(lambda spec: AgentLoop(prov, SlowTools(delay), max_iterations=spec.max_iterations), **kw)
    return mgr, prov


@pytest.mark.asyncio
async def test_spawn_wait_collects_summary_and_counts_tools():
    mgr, _ = _mgr(rounds=2)
    rec = await mgr.spawn(SubagentSpec(goal="do it"), parent_id="main")
    await mgr.wait(rec.id, 5)
    assert rec.state is SubagentState.SUCCEEDED and rec.summary == "all done" and rec.tool_calls == 2


@pytest.mark.asyncio
async def test_steer_reaches_running_child():
    mgr, prov = _mgr(rounds=6, delay=0.05)
    rec = await mgr.spawn(SubagentSpec(goal="long job"), parent_id="main")
    await asyncio.sleep(0.08)
    assert mgr.steer(rec.id, "focus on tests") is True
    await mgr.wait(rec.id, 5)
    assert any("focus on tests" in u for u in prov.seen_user_rows)
    assert mgr.steer(rec.id, "too late") is False  # finished


@pytest.mark.asyncio
async def test_stop_cancels_running_child():
    mgr, _ = _mgr(rounds=1000, delay=0.05)
    rec = await mgr.spawn(SubagentSpec(goal="forever", max_iterations=1000), parent_id="main")
    await asyncio.sleep(0.1)
    out = await mgr.stop(rec.id)
    assert out["accepted"] and rec.state is SubagentState.CANCELLED
    assert (await mgr.stop(rec.id))["already_terminal"]


@pytest.mark.asyncio
async def test_depth_limit_blocks_grandchildren():
    mgr, _ = _mgr()
    child = await mgr.spawn(SubagentSpec(goal="a"), parent_id="main")
    with pytest.raises(SubagentError):
        await mgr.spawn(SubagentSpec(goal="b"), parent_id=child.id)
    await mgr.wait(child.id, 5)


@pytest.mark.asyncio
async def test_concurrency_cap():
    mgr, _ = _mgr(rounds=2, delay=0.1, max_concurrent=1)
    a = await mgr.spawn(SubagentSpec(goal="a"), parent_id="main")
    b = await mgr.spawn(SubagentSpec(goal="b"), parent_id="main")
    await asyncio.sleep(0.05)
    assert a.state is SubagentState.RUNNING and b.state is SubagentState.PENDING
    await mgr.wait(a.id, 5), await mgr.wait(b.id, 5)
    assert b.state is SubagentState.SUCCEEDED


@pytest.mark.asyncio
async def test_completion_notes_delivered_once():
    mgr, _ = _mgr(rounds=1)
    rec = await mgr.spawn(SubagentSpec(goal="bg"), parent_id="main")
    await mgr.wait(rec.id, 5)
    notes = mgr.completion_notes("main")
    assert len(notes) == 1 and "all done" in notes[0]
    assert mgr.completion_notes("main") == []


@pytest.mark.asyncio
async def test_parent_loop_receives_background_result_on_tool_result():
    mgr, _ = _mgr(rounds=1)
    rec = await mgr.spawn(SubagentSpec(goal="bg"), parent_id="main")
    await mgr.wait(rec.id, 5)

    parent_prov = LoopingProvider(rounds=1, answer="parent done")
    parent = AgentLoop(parent_prov, SlowTools(0), notes_source=mgr.completion_notes)
    events = [e async for e in parent.run([__import__("anvil_agent.models.types", fromlist=["ChatMessage"]).ChatMessage(role="user", content="go")])]
    assert events[-1]["type"] == "done"


@pytest.mark.asyncio
async def test_env_is_visible_to_child_task():
    seen = {}

    class EnvTools(SlowTools):
        async def execute(self, tc):
            seen.update(current_agent_env.get())
            return ToolResult(id=tc.id, content="ok")

    prov = LoopingProvider(1)
    mgr = SubagentManager(lambda spec: AgentLoop(prov, EnvTools(0)))
    rec = await mgr.spawn(SubagentSpec(goal="x", env={"kanban_task": "t_1"}), parent_id="main")
    await mgr.wait(rec.id, 5)
    assert seen == {"kanban_task": "t_1"}


@pytest.mark.asyncio
async def test_delegate_tool_foreground_background_and_controls():
    mgr, _ = _mgr(rounds=2, delay=0.05)
    tool = DelegateTool(lambda: mgr)
    res = await tool.execute({"goal": "quick"})
    assert json.loads(res.content)["state"] == "succeeded"

    res = await tool.execute({"goal": "slow", "background": True})
    sid = json.loads(res.content)["id"]
    listed = json.loads((await tool.execute({"action": "list"})).content)["subagents"]
    assert any(s["id"] == sid for s in listed)
    assert json.loads((await tool.execute({"action": "stop", "subagent_id": sid})).content)["accepted"]
    assert (await tool.execute({"action": "steer", "subagent_id": "nope", "message": "x"})).is_error


@pytest.mark.asyncio
async def test_steer_prevents_early_finish():
    """A steer queued while the model is answering is honored instead of dropped."""
    prov = LoopingProvider(rounds=0, answer="first answer")
    loop = AgentLoop(prov, SlowTools(0))
    loop.steer("also do X")
    from anvil_agent.models.types import ChatMessage
    events = [e async for e in loop.run([ChatMessage(role="user", content="hi")])]
    assert any("also do X" in u for u in prov.seen_user_rows) and events[-1]["type"] == "done"


@pytest.mark.asyncio
async def test_child_permission_request_ids_are_namespaced():
    from anvil_agent.agent_loop import AgentLoop
    from anvil_agent.models.types import ChatChunk, ToolCallDelta
    from anvil_agent.permissions import PermissionManager
    from anvil_agent.tools.registry import ToolRegistry
    from anvil_agent.tools.base import Tool
    from anvil_agent.models.types import ToolResult
    import asyncio

    class T(Tool):
        name = "danger"; description = "d"; parameters = {"type": "object", "properties": {}}
        async def execute(self, a): return ToolResult(id="", content="ok")

    class P:
        n = 0
        async def chat(self, *a, **k):
            P.n += 1
            if P.n == 1:
                yield ChatChunk(tool_call_delta=ToolCallDelta(id="call_0", name="danger"))
                yield ChatChunk(tool_call_delta=ToolCallDelta(id="call_0", arguments_delta="{}"))
                yield ChatChunk(finish_reason="tool_use")
            else:
                yield ChatChunk(delta_text="done")
                yield ChatChunk(finish_reason="stop")
        async def health_check(self): return True

    pm = PermissionManager()
    reg = ToolRegistry(); reg.register(T())
    loop = AgentLoop(provider=P(), tool_registry=reg, permission_manager=pm, agent_id="sa_1")
    from anvil_agent.models.types import ChatMessage
    seen = []
    async for ev in loop.run([ChatMessage(role="user", content="go")]):
        if ev.get("type") == "permission_request":
            seen.append(ev["request_id"])
            asyncio.get_running_loop().call_later(0.05, pm.respond, ev["request_id"], True)
    assert seen == ["sa_1:call_0"]
