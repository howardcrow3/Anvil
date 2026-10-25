"""JSON-RPC 2.0 IPC server over a Unix domain socket and/or an authenticated local WebSocket.

The Unix socket serves the native macOS app. The WebSocket (``/rpc``) serves the cross-platform
Electron app and works on Windows, where Unix sockets are unavailable.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
from pathlib import Path
from typing import Any, Callable, Coroutine

from aiohttp import WSMsgType, web

from anvil_agent.ipc.protocol import (
    INTERNAL_ERROR,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    JsonRpcError,
    JsonRpcNotification,
    JsonRpcRequest,
    JsonRpcResponse,
)

logger = logging.getLogger(__name__)

MethodHandler = Callable[..., Coroutine[Any, Any, Any]]


# Origins a browser page may connect from. Requests with no Origin header (non-browser clients) are
# allowed; the per-launch token is the real access control and this is defence in depth.
DEFAULT_WS_ORIGINS = frozenset({"null", "file://", "http://localhost:5173", "http://127.0.0.1:5173"})


class WebSocketWriter:
    """Gives a WebSocket the small ``write()/drain()`` surface request handlers use on a StreamWriter."""

    def __init__(self, ws: web.WebSocketResponse) -> None:
        self._ws = ws
        self._pending: list[str] = []
        self._lock = asyncio.Lock()

    def write(self, data: bytes) -> None:
        self._pending.append(data.decode().rstrip("\n"))

    async def drain(self) -> None:
        async with self._lock:  # keep frames in order when several coroutines flush at once
            pending, self._pending = self._pending, []
            for text in pending:
                await self._ws.send_str(text)

    def close(self) -> None:
        asyncio.ensure_future(self._ws.close())

    def is_closing(self) -> bool:
        return self._ws.closed


class IPCServer:
    """Async JSON-RPC 2.0 server over a Unix domain socket and/or a local WebSocket."""

    def __init__(self, socket_path: str | None = None) -> None:
        self._socket_path = Path(socket_path) if socket_path else None
        self._methods: dict[str, MethodHandler] = {}
        self._server: asyncio.Server | None = None
        self._writers: list[Any] = []
        self._ws_runner: web.AppRunner | None = None
        self._ws_token = ""
        self._ws_origins: frozenset[str] = DEFAULT_WS_ORIGINS

    def register_method(self, name: str, handler: MethodHandler) -> None:
        self._methods[name] = handler

    async def start(self) -> None:
        """Start the Unix socket listener (no-op when no socket path was given)."""
        if self._socket_path is None:
            return
        if self._socket_path.exists():
            self._socket_path.unlink()
        self._socket_path.parent.mkdir(parents=True, exist_ok=True)

        self._server = await asyncio.start_unix_server(
            self._handle_client, path=str(self._socket_path)
        )
        logger.info("IPC server listening on %s", self._socket_path)

    async def start_websocket(
        self,
        token: str,
        host: str = "127.0.0.1",
        port: int = 0,
        allowed_origins: frozenset[str] | None = None,
    ) -> int:
        """Listen for WebSocket clients at ``ws://host:port/rpc?token=...``. Returns the bound port."""
        if not token:
            raise ValueError("a WebSocket token is required")
        self._ws_token = token
        if allowed_origins is not None:
            self._ws_origins = allowed_origins
        app = web.Application()
        app.router.add_get("/rpc", self._handle_ws)
        self._ws_runner = web.AppRunner(app)
        await self._ws_runner.setup()
        await web.TCPSite(self._ws_runner, host, port).start()
        bound = self._ws_runner.addresses[0][1]
        logger.info("IPC WebSocket listening on ws://%s:%d/rpc", host, bound)
        return bound

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        if self._ws_runner:
            await self._ws_runner.cleanup()
            self._ws_runner = None
        for writer in self._writers:
            writer.close()
        if self._socket_path is not None and self._socket_path.exists():
            self._socket_path.unlink()
        logger.info("IPC server stopped")

    async def broadcast_notification(self, method: str, params: dict[str, Any]) -> None:
        """Send a notification to all connected clients."""
        notification = JsonRpcNotification(method=method, params=params)
        data = notification.model_dump_json() + "\n"
        for writer in list(self._writers):
            try:
                writer.write(data.encode())
                await writer.drain()
            except Exception:
                self._writers.remove(writer)

    async def _handle_ws(self, request: web.Request) -> web.StreamResponse:
        origin = request.headers.get("Origin")
        if origin is not None and origin not in self._ws_origins:
            return web.Response(status=403, text="origin not allowed")
        supplied = request.query.get("token", "")
        if not hmac.compare_digest(supplied.encode(), self._ws_token.encode()):
            return web.Response(status=401, text="invalid token")

        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=32 * 1024 * 1024)
        await ws.prepare(request)
        writer = WebSocketWriter(ws)
        self._writers.append(writer)
        logger.info("WebSocket client connected")
        # Each request runs as its own task: a long chat.send must not block chat.cancel or
        # permission.respond arriving on the same connection.
        tasks: set[asyncio.Task[None]] = set()
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    task = asyncio.create_task(self._process_message(msg.data.encode(), writer))
                    tasks.add(task)
                    task.add_done_callback(tasks.discard)
                elif msg.type == WSMsgType.ERROR:
                    break
        finally:
            for task in tasks:
                task.cancel()
            if writer in self._writers:
                self._writers.remove(writer)
            logger.info("WebSocket client disconnected")
        return ws

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self._writers.append(writer)
        logger.info("Client connected")
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                await self._process_message(line, writer)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Client error: %s", e)
        finally:
            if writer in self._writers:
                self._writers.remove(writer)
            writer.close()
            logger.info("Client disconnected")

    async def _process_message(
        self, data: bytes, writer: Any
    ) -> None:
        try:
            raw = json.loads(data)
        except json.JSONDecodeError:
            await self._send_response(
                writer,
                JsonRpcResponse(
                    error=JsonRpcError(code=PARSE_ERROR, message="Parse error"),
                    id=None,
                ),
            )
            return

        try:
            request = JsonRpcRequest(**raw)
        except Exception:
            await self._send_response(
                writer,
                JsonRpcResponse(
                    error=JsonRpcError(code=INVALID_REQUEST, message="Invalid request"),
                    id=raw.get("id"),
                ),
            )
            return

        handler = self._methods.get(request.method)
        if handler is None:
            await self._send_response(
                writer,
                JsonRpcResponse(
                    error=JsonRpcError(
                        code=METHOD_NOT_FOUND,
                        message=f"Method not found: {request.method}",
                    ),
                    id=request.id,
                ),
            )
            return

        try:
            result = await handler(request.params, writer)
            if request.id is not None:
                await self._send_response(
                    writer,
                    JsonRpcResponse(result=result, id=request.id),
                )
        except Exception as e:
            logger.exception("Error handling %s", request.method)
            if request.id is not None:
                await self._send_response(
                    writer,
                    JsonRpcResponse(
                        error=JsonRpcError(code=INTERNAL_ERROR, message=str(e)),
                        id=request.id,
                    ),
                )

    async def _send_response(
        self, writer: Any, response: JsonRpcResponse
    ) -> None:
        data = response.model_dump_json() + "\n"
        writer.write(data.encode())
        await writer.drain()

    async def send_notification(
        self, writer: Any, method: str, params: dict[str, Any]
    ) -> None:
        """Send a notification to a specific client."""
        notification = JsonRpcNotification(method=method, params=params)
        data = notification.model_dump_json() + "\n"
        writer.write(data.encode())
        await writer.drain()
