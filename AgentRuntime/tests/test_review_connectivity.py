"""Regression tests for issues found in the connectivity code review (webhook, Ollama, MCP stdio env)."""

from __future__ import annotations

import asyncio
import socket
from unittest.mock import AsyncMock

import aiohttp
import pytest

from anvil_agent.gateway.adapters.webhook import WebhookAdapter, callback_url_allowed, is_loopback_host
from anvil_agent.gateway.config import WebhookConfig
from anvil_agent.mcp.client import MCPServerConnection
from anvil_agent.services.ollama_service import OllamaService


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ── Webhook adapter ─────────────────────────────────────────────────────────


def test_webhook_listens_on_loopback_by_default():
    assert WebhookConfig().host == "127.0.0.1"


@pytest.mark.parametrize("host,expected", [("127.0.0.1", True), ("::1", True), ("localhost", True), ("0.0.0.0", False), ("192.168.1.5", False), ("example.com", False)])
def test_is_loopback_host(host, expected):
    assert is_loopback_host(host) is expected


async def test_webhook_refuses_to_start_exposed_without_a_secret():
    adapter = WebhookAdapter(WebhookConfig(enabled=True, host="0.0.0.0", port=free_port()))
    with pytest.raises(ValueError, match="hmac_secret"):
        await adapter.start()


@pytest.fixture
async def webhook():
    port = free_port()
    on_message = AsyncMock(return_value="pong")
    adapter = WebhookAdapter(WebhookConfig(enabled=True, port=port, hmac_secret="s3cret", callback_allowed_hosts=["hooks.example.com"]), on_message)
    await adapter.start()
    yield adapter, f"http://127.0.0.1:{port}/webhook/chat", on_message
    await adapter.stop()


def sign(body: bytes, secret="s3cret") -> str:
    import hashlib
    import hmac

    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def post(url, body: bytes, signature: str | None):
    headers = {"Content-Type": "application/json"}
    if signature is not None:
        headers["X-Signature"] = signature
    async with aiohttp.ClientSession() as s, s.post(url, data=body, headers=headers) as r:
        return r.status, await r.json()


async def test_webhook_accepts_a_correctly_signed_request(webhook):
    _, url, on_message = webhook
    body = b'{"message": "ping", "user_id": "u1"}'
    status, data = await post(url, body, sign(body))
    assert status == 200 and data == {"response": "pong"}
    on_message.assert_awaited_once_with("webhook", "u1", "ping")


async def test_webhook_rejects_missing_wrong_and_non_ascii_signatures(webhook):
    _, url, on_message = webhook
    body = b'{"message": "ping"}'
    assert (await post(url, body, None))[0] == 401
    assert (await post(url, body, "deadbeef"))[0] == 401
    # A non-ASCII header used to make compare_digest raise TypeError -> 500.
    assert (await post(url, body, "éé"))[0] == 401
    on_message.assert_not_awaited()


async def test_webhook_blocks_callback_urls_that_are_not_allow_listed(webhook):
    _, url, on_message = webhook
    for target in ("http://169.254.169.254/latest/meta-data", "http://127.0.0.1:9/x", "file:///etc/passwd", "http://evil.example.net/"):
        body = ('{"message": "ping", "callback_url": "%s"}' % target).encode()
        status, data = await post(url, body, sign(body))
        assert status == 400 and "callback_url" in data["error"], target
    on_message.assert_not_awaited()


async def test_webhook_rejects_a_non_object_json_body(webhook):
    _, url, _ = webhook
    body = b'["not", "an", "object"]'
    assert (await post(url, body, sign(body)))[0] == 400


def test_callback_allow_list_matches_host_only():
    allowed = ["hooks.example.com"]
    assert callback_url_allowed("https://hooks.example.com/path?x=1", allowed)
    assert callback_url_allowed("https://HOOKS.example.com/", allowed)
    assert not callback_url_allowed("https://hooks.example.com.evil.net/", allowed)
    assert not callback_url_allowed("https://evil.net/@hooks.example.com", allowed)
    assert not callback_url_allowed("ftp://hooks.example.com/", allowed)
    assert not callback_url_allowed("https://hooks.example.com/", [])


# ── Ollama ──────────────────────────────────────────────────────────────────


async def test_managed_ollama_binds_loopback_and_does_not_inherit_the_ws_token(monkeypatch, tmp_path):
    binary = tmp_path / "ollama"
    binary.write_text("")
    svc = OllamaService()
    captured: dict = {}

    async def fake_exec(*args, **kwargs):
        captured["env"] = kwargs["env"]

        class P:
            pid = 1

        return P()

    monkeypatch.setenv("ANVIL_WS_TOKEN", "secret-token")
    monkeypatch.setattr(svc, "_check_port", AsyncMock(return_value=False))
    monkeypatch.setattr(svc, "_is_port_in_use", AsyncMock(return_value=False))
    monkeypatch.setattr(svc, "_resolve_binary", lambda: str(binary))
    monkeypatch.setattr(svc, "_wait_for_ready", AsyncMock(return_value=True))
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    assert await svc.start() is True
    assert captured["env"]["OLLAMA_HOST"].startswith("127.0.0.1:")
    assert "ANVIL_WS_TOKEN" not in captured["env"]


# ── MCP stdio environment ───────────────────────────────────────────────────


def test_stdio_servers_get_a_minimal_environment_plus_their_own_env(monkeypatch):
    monkeypatch.setenv("ANVIL_WS_TOKEN", "secret-token")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("FORWARDED", "from-parent")
    conn = MCPServerConnection("srv", {"command": "x", "env": {"API_KEY": "mine", "FWD": "${FORWARDED}"}})
    env = conn._build_transport().env
    assert "ANVIL_WS_TOKEN" not in env and "ANTHROPIC_API_KEY" not in env
    assert env["API_KEY"] == "mine"
    assert env["FWD"] == "from-parent"  # opting in via ${VAR} still works
    assert "PATH" in env  # the server can still find its interpreter
