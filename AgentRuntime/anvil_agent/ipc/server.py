"""JSON-RPC 2.0 IPC server over Unix domain socket."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Callable, Coroutine

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


class IPCServer:
    """Async JSON-RPC 2.0 server over Unix domain socket."""

    def __init__(self, socket_path: str) -> None:
        self._socket_path = Path(socket_path)
        self._methods: dict[str, MethodHandler] = {}
        self._server: asyncio.Server | None = None
        self._writers: list[asyncio.StreamWriter] = []

    def register_method(self, name: str, handler: MethodHandler) -> None:
        self._methods[name] = handler

    async def start(self) -> None:
        if self._socket_path.exists():
            self._socket_path.unlink()
        self._socket_path.parent.mkdir(parents=True, exist_ok=True)

        self._server = await asyncio.start_unix_server(
            self._handle_client, path=str(self._socket_path)
        )
        logger.info("IPC server listening on %s", self._socket_path)

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        for writer in self._writers:
            writer.close()
        if self._socket_path.exists():
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
        self, data: bytes, writer: asyncio.StreamWriter
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
        self, writer: asyncio.StreamWriter, response: JsonRpcResponse
    ) -> None:
        data = response.model_dump_json() + "\n"
        writer.write(data.encode())
        await writer.drain()

    async def send_notification(
        self, writer: asyncio.StreamWriter, method: str, params: dict[str, Any]
    ) -> None:
        """Send a notification to a specific client."""
        notification = JsonRpcNotification(method=method, params=params)
        data = notification.model_dump_json() + "\n"
        writer.write(data.encode())
        await writer.drain()
