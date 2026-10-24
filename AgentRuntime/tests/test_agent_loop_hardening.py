import pytest

from anvil_agent.agent_loop import AgentLoop
from anvil_agent.models.router import ModelProvider
from anvil_agent.models.types import ChatChunk, ChatMessage, ToolCallDelta, ToolResult


class ScriptedProvider(ModelProvider):
    model_name = "scripted"
    supports_tool_use = True

    def __init__(self, script):
        self.script = list(script)
        self.seen = []

    async def health_check(self):
        return True

    async def chat(self, messages, tools=None, stream=True):
        self.seen.append((list(messages), tools))
        step = self.script.pop(0) if self.script else {"text": "done"}
        if "tool" in step:
            yield ChatChunk(tool_call_delta=ToolCallDelta(id=step["id"], name=step["tool"]))
            yield ChatChunk(tool_call_delta=ToolCallDelta(id=step["id"], arguments_delta=step.get("args", "{}")))
            yield ChatChunk(finish_reason="tool_use")
        else:
            yield ChatChunk(delta_text=step["text"], finish_reason="end_turn")


class FakeTools:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []

    def get_all_schemas(self):
        return [{"name": "read_file"}]

    async def execute(self, tc):
        self.calls.append(tc)
        return ToolResult(id=tc.id, content="boom" if self.fail else "ok", is_error=self.fail)


async def _run(loop, text="go"):
    return [e async for e in loop.run([ChatMessage(role="user", content=text)])]


@pytest.mark.asyncio
async def test_invalid_json_args_are_reported_not_executed():
    tools = FakeTools()
    prov = ScriptedProvider([{"tool": "read_file", "id": "1", "args": "{not json"}, {"text": "fixed"}])
    events = await _run(AgentLoop(prov, tools, context_window=None))
    assert tools.calls == []
    res = [e for e in events if e["type"] == "tool_result"][0]
    assert res["is_error"] and "Invalid arguments" in res["content"]


@pytest.mark.asyncio
async def test_unattended_loop_halts_on_repeated_identical_failures():
    tools = FakeTools(fail=True)
    prov = ScriptedProvider([{"tool": "read_file", "id": str(i), "args": '{"path":"x"}'} for i in range(20)])
    events = await _run(AgentLoop(prov, tools, unattended=True, max_iterations=20))
    assert events[-1]["stop_reason"] == "tool_loop_halt"
    assert len(tools.calls) < 20


@pytest.mark.asyncio
async def test_budget_exhaustion_makes_toolless_grace_call():
    tools = FakeTools()
    steps = [{"tool": "read_file", "id": str(i), "args": f'{{"path":"{i}"}}'} for i in range(3)]
    prov = ScriptedProvider(steps + [{"text": "summary of progress"}])
    events = await _run(AgentLoop(prov, tools, max_iterations=3))
    assert events[-1]["stop_reason"] == "max_iterations"
    assert any(e.get("text") == "summary of progress" for e in events)
    assert prov.seen[-1][1] is None  # grace call sent no tools


@pytest.mark.asyncio
async def test_nudge_rides_tool_result_not_system_row():
    from anvil_agent.memory.nudger import MemoryNudger

    tools = FakeTools()
    steps = [{"tool": "read_file", "id": str(i), "args": f'{{"path":"{i}"}}'} for i in range(2)] + [{"text": "ok"}]
    prov = ScriptedProvider(steps)
    await _run(AgentLoop(prov, tools, nudger=MemoryNudger(interval=1, max_nudges=1)))
    last_msgs = prov.seen[-1][0]
    assert [m.role for m in last_msgs].count("system") == 1
    assert any("[note]" in m.content for m in last_msgs if m.role == "tool")
