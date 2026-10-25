"""WebSocket transport for the IPC server."""

from __future__ import annotations

import asyncio

import aiohttp
import pytest

from anvil_agent.ipc.server import IPCServer

TOKEN = "test-token-123"


@pytest.fixture
async def server():
    srv = IPCServer(None)  # WebSocket only, as on Windows

    async def echo(params, writer):
        return {"echo": params.get("text")}

    async def stream(params, writer):
        await srv.send_notification(writer, "chat.event", {"type": "text_delta", "text": "hi"})
        return {"status": "ok"}

    gate = asyncio.Event()

    async def slow(params, writer):
        await gate.wait()
        return {"released": True}

    async def release(params, writer):
        gate.set()
        return {"status": "ok"}

    async def boom(params, writer):
        raise RuntimeError("kaboom")

    for name, fn in [("echo", echo), ("stream", stream), ("slow", slow), ("release", release), ("boom", boom)]:
        srv.register_method(name, fn)
    port = await srv.start_websocket(TOKEN)
    srv.port = port  # type: ignore[attr-defined]
    yield srv
    await srv.stop()


def url(srv, token=TOKEN):
    return f"http://127.0.0.1:{srv.port}/rpc?token={token}"


async def rpc(ws, method, params=None, id=1):
    await ws.send_json({"jsonrpc": "2.0", "id": id, "method": method, "params": params or {}})


async def test_round_trip_and_notifications(server):
    async with aiohttp.ClientSession() as http, http.ws_connect(url(server)) as ws:
        await rpc(ws, "echo", {"text": "hello"})
        assert (await ws.receive_json())["result"] == {"echo": "hello"}

        await rpc(ws, "stream", id=2)
        first, second = await ws.receive_json(), await ws.receive_json()
        notification = first if "method" in first else second
        response = second if "method" in first else first
        assert notification["method"] == "chat.event" and notification["params"]["text"] == "hi"
        assert response["id"] == 2 and response["result"] == {"status": "ok"}


async def test_errors_are_json_rpc_errors(server):
    async with aiohttp.ClientSession() as http, http.ws_connect(url(server)) as ws:
        await rpc(ws, "boom")
        assert "kaboom" in (await ws.receive_json())["error"]["message"]
        await rpc(ws, "nope", id=2)
        assert (await ws.receive_json())["error"]["code"] == -32601
        await ws.send_str("not json")
        assert (await ws.receive_json())["error"]["code"] == -32700


async def test_bad_or_missing_token_is_rejected(server):
    async with aiohttp.ClientSession() as http:
        for bad in ("wrong", ""):
            with pytest.raises(aiohttp.WSServerHandshakeError) as exc:
                await http.ws_connect(url(server, bad))
            assert exc.value.status == 401


async def test_foreign_browser_origin_is_rejected_even_with_token(server):
    async with aiohttp.ClientSession() as http:
        with pytest.raises(aiohttp.WSServerHandshakeError) as exc:
            await http.ws_connect(url(server), headers={"Origin": "https://evil.example"})
        assert exc.value.status == 403
        # An allowed origin (the Vite dev server) connects fine.
        async with http.ws_connect(url(server), headers={"Origin": "http://localhost:5173"}) as ws:
            await rpc(ws, "echo", {"text": "ok"})
            assert (await ws.receive_json())["result"] == {"echo": "ok"}


async def test_requests_run_concurrently_on_one_connection(server):
    """A long-running request (chat.send) must not block a later one (chat.cancel)."""
    async with aiohttp.ClientSession() as http, http.ws_connect(url(server)) as ws:
        await rpc(ws, "slow", id=1)
        await rpc(ws, "release", id=2)
        first = await asyncio.wait_for(ws.receive_json(), timeout=5)
        second = await asyncio.wait_for(ws.receive_json(), timeout=5)
        assert {first["id"], second["id"]} == {1, 2}
        assert first["id"] == 2  # release answered first, then the slow call finished


async def test_broadcast_reaches_all_clients(server):
    async with aiohttp.ClientSession() as http:
        async with http.ws_connect(url(server)) as a, http.ws_connect(url(server)) as b:
            await asyncio.sleep(0.1)
            await server.broadcast_notification("task.status", {"x": 1})
            for ws in (a, b):
                msg = await asyncio.wait_for(ws.receive_json(), timeout=5)
                assert msg["method"] == "task.status" and msg["params"] == {"x": 1}


async def test_start_websocket_requires_token():
    with pytest.raises(ValueError):
        await IPCServer(None).start_websocket("")


async def test_runtime_exits_when_launcher_closes_stdin(tmp_path):
    """Orphan protection: if the Electron app dies, the runtime it started must not linger."""
    import os
    import subprocess
    import sys

    env = {**os.environ, "HOME": str(tmp_path), "USERPROFILE": str(tmp_path), "ANVIL_WS_TOKEN": "t"}
    proc = subprocess.Popen(
        [sys.executable, "-u", "-m", "anvil_agent", "--no-socket", "--ws-port", "0", "--exit-on-stdin-eof",
         "--project-dir", str(tmp_path), "--log-level", "ERROR"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env,
        cwd=os.path.join(os.path.dirname(__file__), ".."),
    )
    try:
        loop = asyncio.get_running_loop()

        async def ready() -> None:
            while True:  # log lines can precede the readiness line
                line = await loop.run_in_executor(None, proc.stdout.readline)
                assert line, "runtime exited before becoming ready"
                if line.startswith(b"WS_READY:"):
                    return

        await asyncio.wait_for(ready(), timeout=40)
        assert proc.poll() is None
        proc.stdin.close()  # what the OS does when the launching process dies
        code = await asyncio.wait_for(loop.run_in_executor(None, proc.wait), timeout=20)
        assert code == 0
    finally:
        if proc.poll() is None:
            proc.kill()
