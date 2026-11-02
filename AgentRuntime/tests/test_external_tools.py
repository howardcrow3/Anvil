import json
import os
import stat
import sys

import pytest

from anvil_agent.context import current_agent_id
from anvil_agent.tools import browser_tool, desktop_tool
from anvil_agent.tools.browser_tool import BrowserTool
from anvil_agent.tools.desktop_tool import DesktopTool
from anvil_agent.tools.external_cli import find_binary


def fake_cli(tmp_path, name, body):
    path = tmp_path / name
    path.write_text(f"#!{sys.executable}\nimport sys, os, json\n{body}\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


ECHO = "print(json.dumps({'argv': sys.argv[1:], 'session': os.environ.get('AGENT_BROWSER_SESSION'), 'has_key': 'ANTHROPIC_API_KEY' in os.environ}))"


# ---- argv building / validation -------------------------------------------------------------

def test_browser_argv_basics():
    b = browser_tool.build_argv
    assert b({"action": "open", "url": "https://example.com"}) == ["open", "https://example.com"]
    assert b({"action": "snapshot"}) == ["snapshot", "-i", "-c"]
    assert b({"action": "click", "ref": "@e12"}) == ["click", "@e12"]
    assert b({"action": "fill", "ref": "@e3", "text": "hello world"}) == ["fill", "@e3", "hello world"]
    assert b({"action": "wait", "text": "Done"}) == ["wait", "--text", "Done"]
    assert b({"action": "help"}) == ["skills", "get", "core"]


@pytest.mark.parametrize("args", [
    {"action": "open", "url": "file:///etc/passwd"},
    {"action": "open", "url": "javascript:alert(1)"},
    {"action": "open", "url": "--config=/tmp/x"},
    {"action": "click", "ref": "#submit"},
    {"action": "click", "ref": "@e1; rm -rf /"},
    {"action": "fill", "ref": "@e1", "text": "--allowed-domains evil.com"},
    {"action": "press", "key": "Enter && ls"},
    {"action": "eval", "script": "alert(1)"},
    {"action": "upload", "ref": "@e1"},
    {"action": "wait"},
])
def test_browser_rejects_unsafe(args):
    with pytest.raises(ValueError):
        browser_tool.build_argv(args)


def test_desktop_argv_and_validation():
    d = desktop_tool.build_argv
    assert d({"action": "snapshot", "app": "Finder", "skeleton": True}) == ["snapshot", "--app", "Finder", "--skeleton", "-i", "--compact"]
    assert d({"action": "snapshot", "root": "@s8f3k2p9:e3"}) == ["snapshot", "--root", "@s8f3k2p9:e3", "-i", "--compact"]
    assert d({"action": "click", "ref": "@s8f3k2p9:e8"}) == ["click", "@s8f3k2p9:e8"]
    assert d({"action": "set_value", "ref": "@s8f3k2p9:e2", "text": "x"}) == ["set-value", "@s8f3k2p9:e2", "x"]
    for bad in [
        {"action": "click", "ref": "@e8"},                      # bare refs are rejected by the CLI too
        {"action": "launch", "app": "/usr/bin/evil"},
        {"action": "snapshot", "app": "-x"},
        {"action": "clipboard_get"}, {"action": "drag"}, {"action": "close_app", "app": "Slack"},
        {"action": "press", "key": "cmd+s; ls"},
        {"action": "snapshot", "app": "Finder", "surface": "bogus"},
    ]:
        with pytest.raises(ValueError):
            d(bad)


# ---- execution against fake binaries ---------------------------------------------------------

@pytest.mark.asyncio
async def test_browser_runs_with_isolated_session_and_wraps_output(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-should-not-leak-0000000000")
    binary = fake_cli(tmp_path, "agent-browser", ECHO)
    cfg = {"agent_browser_path": binary, "agent_browser_allowed_domains": ["example.com", "*.example.com"], "agent_browser_max_output": 5000}
    tool = BrowserTool(lambda: cfg)
    token = current_agent_id.set("sa_7")
    try:
        res = await tool.execute({"action": "open", "url": "https://example.com"})
    finally:
        current_agent_id.reset(token)
    assert not res.is_error
    assert res.content.startswith(browser_tool.BANNER) and res.content.rstrip().endswith(browser_tool.BANNER_END)
    payload = json.loads(res.content.split("\n", 1)[1].rsplit("\n", 1)[0])
    assert payload["session"] == "anvil-sa_7"
    assert payload["has_key"] is False                               # secrets are not passed to the child
    argv = payload["argv"]
    assert "--content-boundaries" in argv and argv[argv.index("--allowed-domains") + 1] == "example.com,*.example.com"
    assert argv[-2:] == ["open", "https://example.com"]


@pytest.mark.asyncio
async def test_browser_missing_binary_and_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr("anvil_agent.tools.external_cli.extra_search_dirs", lambda: [])
    monkeypatch.setattr("anvil_agent.tools.external_cli.bundled_dirs", lambda: [])
    res = await BrowserTool(lambda: {}).execute({"action": "open", "url": "https://example.com"})
    assert res.is_error and "agent-browser ships with Anvil" in res.content
    res = await BrowserTool(lambda: {"agent_browser_enabled": False}).execute({"action": "snapshot"})
    assert res.is_error and "disabled" in res.content


@pytest.mark.asyncio
async def test_browser_nonzero_exit_is_error(tmp_path):
    binary = fake_cli(tmp_path, "agent-browser", "sys.stderr.write('boom'); sys.exit(2)")
    res = await BrowserTool(lambda: {"agent_browser_path": binary}).execute({"action": "snapshot"})
    assert res.is_error and "boom" in res.content


@pytest.mark.asyncio
async def test_desktop_envelope_success_and_error(tmp_path):
    ok = fake_cli(tmp_path, "agent-desktop", "print(json.dumps({'ok': True, 'command': 'snapshot', 'data': {'snapshot_id': 's1', 'tree': {'role': 'window'}}}))")
    res = await DesktopTool(lambda: {"agent_desktop_path": ok}).execute({"action": "snapshot", "app": "Finder"})
    assert not res.is_error and desktop_tool.BANNER in res.content and '"snapshot_id":"s1"' in res.content

    err_env = {"ok": False, "error": {"code": "STALE_REF", "message": "gone", "suggestion": "Re-snapshot",
                                      "disposition": {"delivery": "delivered_unverified", "retry": "unsafe"}}}
    bad = fake_cli(tmp_path, "agent-desktop2", f"print(json.dumps({err_env!r}))".replace("False", "False"))
    res = await DesktopTool(lambda: {"agent_desktop_path": bad}).execute({"action": "click", "ref": "@s1:e1"})
    assert res.is_error and "STALE_REF" in res.content and "Retry: unsafe" in res.content and "Do not repeat" in res.content


@pytest.mark.asyncio
async def test_cli_timeout_kills_process(tmp_path):
    from anvil_agent.tools.external_cli import run_cli
    binary = fake_cli(tmp_path, "slow", "import time; time.sleep(30)")
    res = await run_cli(binary, [], timeout=0.5)
    assert res.timed_out


def test_find_binary_override(tmp_path):
    p = fake_cli(tmp_path, "agent-browser", "pass")
    assert find_binary("agent-browser", p) == p
    assert find_binary("agent-browser", str(tmp_path / "nope")) is None


@pytest.mark.parametrize("url,ok", [
    ("example.com", True), ("localhost:3000/app", True), ("http://example.com/a?b=1", True),
    ("about:blank", False), ("data:text/html,hi", False), ("mailto:a@b.c", False),
    ("ftp://example.com", False), ("javascript:alert(1)", False), ("chrome://settings", False),
])
def test_browser_url_policy(url, ok):
    if ok:
        assert browser_tool.build_argv({"action": "open", "url": url}) == ["open", url]
    else:
        with pytest.raises(ValueError):
            browser_tool.build_argv({"action": "open", "url": url})


# ── Bundling / installer ──────────────────────────────────────────────

def test_find_binary_prefers_bundled_dir(tmp_path, monkeypatch):
    import sys
    from anvil_agent.tools.external_cli import find_binary
    name = "fake-tool-xyz" + (".exe" if sys.platform == "win32" else "")
    (tmp_path / name).write_text("#!/bin/sh\n")
    (tmp_path / name).chmod(0o755)
    assert find_binary("fake-tool-xyz") is None
    monkeypatch.setenv("ANVIL_TOOLS_DIR", str(tmp_path))
    assert find_binary("fake-tool-xyz") == str(tmp_path / name)
    # an explicit override still wins and is not silently replaced by the bundled copy
    assert find_binary("fake-tool-xyz", override=str(tmp_path / "nope")) is None


def test_installer_plan_includes_helpers():
    from anvil_agent.tools.installer import plan
    assert plan("agent-browser", "linux-x64") == [("agent-browser-linux-x64", "agent-browser")]
    assert ("agent-desktop-macos-helper-darwin-arm64", "agent-desktop-macos-helper") in plan("agent-desktop", "darwin-arm64")
    assert plan("agent-desktop", "win32-x64") == [("agent-desktop-win32-x64.exe", "agent-desktop.exe")]


def test_installer_unknown_tool_and_unsafe_archive(tmp_path):
    import asyncio, io, tarfile
    from anvil_agent.tools.installer import _safe_extract, install_tool
    assert asyncio.run(install_tool("rm-rf"))["ok"] is False
    bad = tmp_path / "bad.tgz"
    with tarfile.open(bad, "w:gz") as tf:
        info = tarfile.TarInfo("../escape.txt"); info.size = 1
        tf.addfile(info, io.BytesIO(b"x"))
    import pytest
    with pytest.raises(RuntimeError):
        _safe_extract(bad, tmp_path / "out")


# ── DonSeTch (built-in MCP server) ────────────────────────────────────

def _fake_donsetch(tmp_path, monkeypatch):
    import sys
    name = "donsetch" + (".exe" if sys.platform == "win32" else "")
    d = tmp_path / "tools"
    d.mkdir()
    (d / name).write_text("#!/bin/sh\n")
    (d / name).chmod(0o755)
    monkeypatch.setenv("ANVIL_TOOLS_DIR", str(d))
    return str(d / name)


def test_donsetch_is_builtin_mcp_server_with_clean_env(tmp_path, monkeypatch):
    from anvil_agent.mcp.client import MCPClient, MCPServerConnection
    path = _fake_donsetch(tmp_path, monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    client = MCPClient(tmp_path / "mcp.json", builtins=True)
    entry = client.read_entries()["donsetch"]
    assert entry["command"] == path and entry["args"] == ["mcp"] and entry["inherit_env"] is False
    env = MCPServerConnection("donsetch", entry)._build_transport().env
    assert "ANTHROPIC_API_KEY" not in env
    # off unless asked for (existing callers/tests stay hermetic)
    assert "donsetch" not in MCPClient(tmp_path / "mcp.json").read_entries()


def test_builtin_not_frozen_into_config_and_user_entry_wins(tmp_path, monkeypatch):
    import json
    from anvil_agent.mcp.client import MCPClient
    _fake_donsetch(tmp_path, monkeypatch)
    cfg = tmp_path / "mcp.json"
    client = MCPClient(cfg, builtins=True)
    client.write_servers(client.list_servers())          # UI round-trip of the untouched list
    assert "donsetch" not in json.loads(cfg.read_text())["mcpServers"]
    servers = client.list_servers()
    servers[0]["enabled"] = False                         # user disables it -> persisted override
    client.write_servers(servers)
    saved = json.loads(cfg.read_text())["mcpServers"]["donsetch"]
    assert saved["enabled"] is False and saved["inherit_env"] is False and "builtin" not in saved
    assert client.list_servers()[0]["status"] == "disabled"


def test_donsetch_pins_match_fetch_script():
    import re
    from pathlib import Path
    from anvil_agent.tools.installer import DONSETCH_VERSION, PINNED_DONSETCH
    js = (Path(__file__).resolve().parents[2] / "Scripts" / "fetch-agent-tools.mjs").read_text()
    assert f"'{DONSETCH_VERSION}'" in js
    for key, sha in PINNED_DONSETCH.items():
        assert re.search(rf"'{key}': '{sha}'", js), key
