import json

import pytest

from anvil_agent.models.types import ToolCallRequest, ToolResult
from anvil_agent.tools import create_default_registry
from anvil_agent.tools.base import Tool
from anvil_agent.tools.registry import ToolRegistry
from anvil_agent.tools.tool_search import search_docs, _Doc, tokenize


class Dummy(Tool):
    parameters = {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}

    def __init__(self, name, description, defer=False):
        self.name, self.description, self.defer = name, description, defer

    async def execute(self, arguments):
        return ToolResult(id="", content=f"{self.name}:{arguments}")


def _registry():
    r = ToolRegistry()
    r.register(Dummy("read_file", "Read a file from disk."))
    r.register(Dummy("github_create_issue", "Create an issue in a GitHub repository.", defer=True))
    r.register(Dummy("github_list_pulls", "List open pull requests.", defer=True))
    r.register(Dummy("slack_send_message", "Send a message to a Slack channel.", defer=True))
    return r


def test_deferred_tools_replaced_by_bridge():
    names = [s["name"] for s in _registry().get_all_schemas()]
    assert names[0] == "read_file" and set(names[1:]) == {"tool_search", "tool_describe", "tool_call"}


def test_off_mode_exposes_everything():
    r = _registry()
    r.tool_search = "off"
    assert len(r.get_all_schemas()) == 4


def test_no_deferred_tools_no_bridge():
    r = ToolRegistry()
    r.register(Dummy("a", "x"))
    assert [s["name"] for s in r.get_all_schemas()] == ["a"]


def test_listing_is_sorted_and_embedded():
    desc = next(s for s in _registry().get_all_schemas() if s["name"] == "tool_search")["description"]
    assert desc.index("github_create_issue") < desc.index("slack_send_message")


def test_stemming_matches_plural_and_name_words():
    assert tokenize("issues") == tokenize("create_issue")[1:] or tokenize("issues")[0] in tokenize("create_issue")
    docs = [_Doc("github_create_issue", {"description": "Create an issue.", "parameters": {"properties": {"title": {}}}}),
            _Doc("slack_send_message", {"description": "Send a message.", "parameters": {"properties": {}}})]
    assert search_docs(docs, "create issues")[0].name == "github_create_issue"
    assert search_docs(docs, "slack_send_message")[0].name == "slack_send_message"
    assert search_docs(docs, "kubernetes") == []


@pytest.mark.asyncio
async def test_search_describe_call_roundtrip():
    r = _registry()
    res = await r.execute(ToolCallRequest(id="1", name="tool_search", arguments={"queries": ["open a github issue"]}))
    assert json.loads(res.content)["results"][0]["matches"][0]["name"] == "github_create_issue"
    res = await r.execute(ToolCallRequest(id="2", name="tool_describe", arguments={"names": ["github_create_issue", "read_file"]}))
    body = json.loads(res.content)
    assert "github_create_issue" in body["schemas"] and body["not_deferred_or_unknown"] == ["read_file"]
    res = await r.execute(ToolCallRequest(id="3", name="tool_call", arguments={"name": "slack_send_message", "arguments": {"q": "hi"}}))
    assert res.content.startswith("slack_send_message:") and res.id == "3"


@pytest.mark.asyncio
async def test_tool_call_refuses_non_deferred_and_unknown():
    r = _registry()
    for name in ("read_file", "nope"):
        res = await r.execute(ToolCallRequest(id="x", name="tool_call", arguments={"name": name, "arguments": {}}))
        assert res.is_error


def test_unwrap_reveals_inner_tool_for_permissions():
    r = _registry()
    req = ToolCallRequest(id="1", name="tool_call", arguments={"name": "slack_send_message", "arguments": {"q": "x"}})
    name, args = r.unwrap(req)
    assert name == "slack_send_message" and args is req.arguments["arguments"]


def test_bridge_names_are_reserved():
    with pytest.raises(ValueError):
        ToolRegistry().register(Dummy("tool_call", "x"))


def test_filtered_registry_keeps_deferral():
    f = _registry().filtered(blocked=["slack_send_message"])
    assert "slack_send_message" not in f.tool_names and f.search_active


def test_default_registry_defers_web_tools_and_shrinks_schema():
    r = create_default_registry()
    visible = [s["name"] for s in r.get_all_schemas()]
    assert "web_search" not in visible and "tool_search" in visible and "read_file" in visible
    r.tool_search = "off"
    assert "web_search" in [s["name"] for s in r.get_all_schemas()]
