"""MCP client tests against a real stdio/HTTP test server (tests/fixtures/mcp_test_server.py)."""

from __future__ import annotations

import asyncio
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from anvil_agent.mcp.client import MCPClient, MCPServerConnection, format_call_result, make_tool_name
from anvil_agent.models.types import ToolCallRequest
from anvil_agent.tools.registry import ToolRegistry

SERVER = str(Path(__file__).parent / "fixtures" / "mcp_test_server.py")


def _write_config(tmp_path: Path, servers: dict) -> Path:
    path = tmp_path / "mcp-servers.json"
    path.write_text(json.dumps({"mcpServers": servers}))
    return path


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_make_tool_name_sanitizes_and_caps():
    assert make_tool_name("my server", "do.thing") == "mcp__my_server__do_thing"
    long = make_tool_name("s", "t" * 100)
    assert len(long) <= 64 and long.startswith("mcp__s__")
    assert make_tool_name("s", "t" * 100) == long  # deterministic
    assert make_tool_name("s", "t" * 99 + "x") != long  # hash disambiguates truncation


async def test_stdio_server_registers_and_calls_with_remote_name(tmp_path):
    cfg = _write_config(tmp_path, {"t": {"command": sys.executable, "args": [SERVER]}})
    registry, client = ToolRegistry(), MCPClient(cfg)
    try:
        await client.load_and_start(registry)
        assert {"mcp__t__add", "mcp__t__echo", "mcp__t__boom"} <= set(registry.tool_names)
        # Regression: the server must receive its own tool name, not the mcp__t__ prefixed one.
        res = await registry.execute(ToolCallRequest(id="1", name="mcp__t__echo", arguments={"text": "hi"}))
        assert not res.is_error and res.id == "1" and "echo:hi" in res.content
        res = await registry.execute(ToolCallRequest(id="2", name="mcp__t__add", arguments={"a": 2, "b": 3}))
        assert "5" in res.content
        assert client.status()["connected"]["t"]["transport"] == "stdio"
    finally:
        await client.stop_all(registry)
    assert "mcp__t__add" not in registry.tool_names


async def test_tool_error_is_reported_as_error(tmp_path):
    cfg = _write_config(tmp_path, {"t": {"command": sys.executable, "args": [SERVER]}})
    registry, client = ToolRegistry(), MCPClient(cfg)
    try:
        await client.load_and_start(registry)
        res = await registry.execute(ToolCallRequest(id="1", name="mcp__t__boom", arguments={}))
        assert res.is_error and "boom" in res.content
    finally:
        await client.stop_all(registry)


async def test_streamable_http_server(tmp_path):
    port = _free_port()
    proc = subprocess.Popen([sys.executable, SERVER, "http", str(port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
                break
            except OSError:
                await asyncio.sleep(0.2)
        cfg = _write_config(tmp_path, {"web": {"url": f"http://127.0.0.1:{port}/mcp", "headers": {"X-Test": "1"}}})
        registry, client = ToolRegistry(), MCPClient(cfg)
        try:
            await client.load_and_start(registry)
            assert "mcp__web__add" in registry.tool_names
            res = await registry.execute(ToolCallRequest(id="1", name="mcp__web__add", arguments={"a": 4, "b": 5}))
            assert "9" in res.content
            assert client.status()["connected"]["web"]["transport"] == "http"
        finally:
            await client.stop_all(registry)
    finally:
        proc.terminate()
        proc.wait(timeout=10)


async def test_bad_and_disabled_servers_do_not_block_good_ones(tmp_path):
    cfg = _write_config(
        tmp_path,
        {
            "good": {"command": sys.executable, "args": [SERVER]},
            "bad": {"command": "/nonexistent/binary"},
            "off": {"command": sys.executable, "args": [SERVER], "enabled": False},
        },
    )
    registry, client = ToolRegistry(), MCPClient(cfg)
    try:
        await client.load_and_start(registry)
        assert "mcp__good__add" in registry.tool_names
        assert not any(n.startswith("mcp__off__") for n in registry.tool_names)
        assert "bad" in client.status()["failed"]
    finally:
        await client.stop_all(registry)


async def test_missing_config_is_a_noop(tmp_path):
    registry = ToolRegistry()
    await MCPClient(tmp_path / "nope.json").load_and_start(registry)
    assert registry.tool_names == []


async def test_connection_requires_command_or_url():
    conn = MCPServerConnection("x", {})
    with pytest.raises(RuntimeError):
        await conn.start()


def test_format_call_result_handles_non_text_blocks():
    from mcp import types

    result = types.CallToolResult(
        content=[
            types.TextContent(type="text", text="hello"),
            types.ImageContent(type="image", data="AAAA", mime_type="image/png"),
        ]
    )
    out = format_call_result(result)
    assert "hello" in out and "[image: image/png" in out


# -- settings-dialog support: read/write config, status, test, reload ---------------------------


def _stdio_server(name: str = "t", **extra) -> dict:
    return {"name": name, "transport": "stdio", "command": sys.executable, "args": [SERVER], "enabled": True, **extra}


async def test_write_servers_roundtrip_and_permissions(tmp_path):
    client = MCPClient(tmp_path / "mcp-servers.json")
    client.write_servers(
        [
            _stdio_server("a", env={"K": "v"}, cwd="/tmp", timeout=12),
            {"name": "b", "transport": "http", "url": "https://x.test/mcp", "headers": {"Authorization": "Bearer ${T}"}, "enabled": False},
            {"name": "c", "transport": "sse", "url": "https://x.test/sse"},
        ]
    )
    assert (tmp_path / "mcp-servers.json").stat().st_mode & 0o777 == 0o600
    listed = {s["name"]: s for s in client.list_servers()}
    assert listed["a"]["transport"] == "stdio" and listed["a"]["env"] == {"K": "v"} and listed["a"]["timeout"] == 12
    assert listed["b"]["transport"] == "http" and listed["b"]["status"] == "disabled"
    assert listed["b"]["headers"] == {"Authorization": "Bearer ${T}"}
    assert listed["c"]["transport"] == "sse"
    assert listed["a"]["status"] == "stopped"  # configured, not started


def test_write_servers_preserves_unknown_keys_and_rejects_bad_input(tmp_path):
    path = tmp_path / "mcp-servers.json"
    path.write_text(json.dumps({"mcpServers": {"a": {"command": "x", "connect_timeout": 5, "custom": 1}}, "other": 7}))
    client = MCPClient(path)
    client.write_servers([{"name": "a", "transport": "stdio", "command": "y"}])
    saved = json.loads(path.read_text())
    assert saved["other"] == 7
    assert saved["mcpServers"]["a"] == {"command": "y", "connect_timeout": 5, "custom": 1}

    for bad in (
        [{"name": "", "transport": "stdio", "command": "x"}],
        [{"name": "a", "transport": "stdio", "command": " "}],
        [{"name": "a", "transport": "http", "url": "ftp://nope"}],
        [{"name": "a", "transport": "carrier-pigeon"}],
        [_stdio_server("dup"), _stdio_server("dup")],
    ):
        with pytest.raises(ValueError):
            client.write_servers(bad)
    assert json.loads(path.read_text()) == saved  # failed writes leave the file untouched


async def test_test_server_reports_tools_and_errors(tmp_path):
    client = MCPClient(tmp_path / "c.json")
    ok = await client.test_server(_stdio_server())
    assert ok["ok"] and {"add", "echo", "boom"} <= {t["name"] for t in ok["tools"]}
    bad = await client.test_server(_stdio_server(command="/nonexistent/binary"))
    assert not bad["ok"] and bad["error"]
    invalid = await client.test_server({"name": "", "transport": "stdio"})
    assert not invalid["ok"]


async def test_reload_picks_up_edits_and_reports_status(tmp_path):
    registry, client = ToolRegistry(), MCPClient(tmp_path / "c.json")
    client.write_servers([_stdio_server("one")])
    try:
        await client.reload(registry)
        s = client.list_servers()[0]
        assert s["status"] == "connected" and {t["name"] for t in s["tools"]} >= {"mcp__one__add"}

        client.write_servers([_stdio_server("two"), _stdio_server("broken", command="/nonexistent/binary")])
        await client.reload(registry)
        assert "mcp__one__add" not in registry.tool_names and "mcp__two__add" in registry.tool_names
        states = {s["name"]: s["status"] for s in client.list_servers()}
        assert states == {"two": "connected", "broken": "failed"}
        assert client.list_servers()[1]["error"]
    finally:
        await client.stop_all(registry)
