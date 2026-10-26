"""Regression tests for review findings in main.py wiring and the subagent manager."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from anvil_agent.agent_loop import AgentLoop
from anvil_agent.main import AnvilRuntime
from anvil_agent.models.claude_provider import ClaudeProvider
from anvil_agent.models.router import ModelProvider, ModelRouter
from anvil_agent.models.types import ChatChunk, ToolCallDelta, ToolResult
from anvil_agent.subagents import SubagentManager, SubagentSpec
from anvil_agent.subagents.manager import NonInteractivePermissions
from anvil_agent.tools.registry import ToolRegistry


class _Allow:
    def check_sync(self, name):  # noqa: D401
        return "ask"


def _stub(api_key_models=()):
    router = ModelRouter()
    stub = SimpleNamespace(
        _router=router,
        _settings={"default_model": "claude-sonnet-5-5"},
        _system_prompt="sp",
        _project_dir="/tmp",
        _tool_registry=ToolRegistry(),
        _permission_manager=_Allow(),
        _agent_loop=None,
        rebuilt=0,
    )
    stub._settings = SimpleNamespace(get=lambda k, d=None: {"default_model": "claude-sonnet-5-5"}.get(k, d))

    def rebuild():
        stub.rebuilt += 1

    stub._rebuild_agent_loop = rebuild
    return stub


def test_api_key_replacement_swaps_providers_and_rebuilds_loop():
    s = _stub()
    AnvilRuntime._apply_api_key(s, "sk-one")
    first = s._router.active
    assert isinstance(first, ClaudeProvider) and s._router.active_model_id == "claude-sonnet-5-5"
    AnvilRuntime._apply_api_key(s, "sk-two")
    assert s._router.active is not first, "replaced key must produce a fresh provider"
    assert s.rebuilt == 2


def test_api_key_removal_unregisters_cloud_models_but_keeps_others():
    s = _stub()

    class Local(ModelProvider):
        model_name = "local"

        async def health_check(self):
            return True

        async def chat(self, messages, tools=None, stream=True):
            yield ChatChunk(delta_text="x")

    AnvilRuntime._apply_api_key(s, "sk-one")
    s._router.register("custom:x", Local(), provider_type="custom")
    AnvilRuntime._apply_api_key(s, "")
    ids = [m["id"] for m in s._router.list_models()]
    assert ids == ["custom:x"] and s._router.active_model_id == "custom:x"


def test_gateway_loop_uses_non_interactive_permissions():
    s = _stub()
    s._router.register("m", _P())
    loop = AnvilRuntime._gateway_agent_loop(s)
    assert isinstance(loop, AgentLoop)
    pm = loop._permission_manager
    assert isinstance(pm, NonInteractivePermissions)
    assert pm.check_sync("bash") == "deny"          # would have prompted a human who is not there
    assert pm.check_sync("read_file") == "allow"    # read-only still works


class _P(ModelProvider):
    model_name = "p"

    async def health_check(self):
        return True

    async def chat(self, messages, tools=None, stream=True):
        yield ChatChunk(delta_text="x")


class _NarratingProvider(ModelProvider):
    """Says 'Let me check' + calls a tool, then gives the real answer."""

    model_name = "n"

    async def health_check(self):
        return True

    async def chat(self, messages, tools=None, stream=True):
        if not any(m.role == "tool" for m in messages):
            yield ChatChunk(delta_text="Let me check the files. ")
            yield ChatChunk(tool_call_delta=ToolCallDelta(id="t", name="work"))
            yield ChatChunk(tool_call_delta=ToolCallDelta(id="t", arguments_delta="{}"))
            yield ChatChunk(finish_reason="tool_use")
        else:
            yield ChatChunk(delta_text="FINAL ANSWER", finish_reason="end_turn")


class _Tools:
    def get_all_schemas(self):
        return [{"name": "work"}]

    async def execute(self, tc):
        return ToolResult(id=tc.id, content="ok")


@pytest.mark.asyncio
async def test_subagent_summary_excludes_pre_tool_narration():
    mgr = SubagentManager(lambda spec: AgentLoop(_NarratingProvider(), _Tools(), max_iterations=spec.max_iterations))
    rec = await mgr.spawn(SubagentSpec(goal="g"), parent_id="main")
    await mgr.wait(rec.id, 5)
    assert rec.summary == "FINAL ANSWER"
