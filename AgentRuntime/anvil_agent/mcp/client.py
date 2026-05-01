"""MCP (Model Context Protocol) client - manages MCP server subprocesses."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from pathlib import Path
from typing import Any

from anvil_agent.models.types import ToolResult
from anvil_agent.tools.base import Tool
from anvil_agent.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

MCP_CONFIG_PATH = Path.home() / ".anvil" / "mcp-servers.json"


class MCPTool(Tool):
    """A tool backed by an MCP server."""

    requires_approval = True

    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        server: MCPServerConnection,
    ) -> None:
        self.name = name
        self.description = description
        self.parameters = parameters
        self._server = server

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return await self._server.call_tool(self.name, arguments)


class MCPServerConnection:
    """Manages a single MCP server subprocess."""

    def __init__(self, name: str, command: str, args: list[str], env: dict[str, str] | None = None) -> None:
        self.name = name
        self._command = command
        self._args = args
        self._env = env
        self._process: asyncio.subprocess.Process | None = None
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._pending: dict[str, asyncio.Future[Any]] = {}
        self._read_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start the MCP server subprocess."""
        self._process = await asyncio.create_subprocess_exec(
            self._command,
            *self._args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._env,
        )
        self._reader = self._process.stdout
        self._writer_raw = self._process.stdin
        self._read_task = asyncio.create_task(self._read_loop())

        # Initialize with MCP protocol
        await self._send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "anvil", "version": "0.1.0"},
        })
        await self._send_notification("notifications/initialized", {})

    async def stop(self) -> None:
        if self._read_task:
            self._read_task.cancel()
        if self._process:
            self._process.terminate()
            await self._process.wait()

    async def list_tools(self) -> list[dict[str, Any]]:
        """Get available tools from the MCP server."""
        result = await self._send_request("tools/list", {})
        return result.get("tools", [])

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Call a tool on the MCP server."""
        try:
            result = await self._send_request("tools/call", {
                "name": name,
                "arguments": arguments,
            })
            content_parts = []
            for item in result.get("content", []):
                if item.get("type") == "text":
                    content_parts.append(item.get("text", ""))
            return ToolResult(
                id="",
                content="\n".join(content_parts) if content_parts else json.dumps(result),
                is_error=result.get("isError", False),
            )
        except Exception as e:
            return ToolResult(id="", content=f"MCP error: {e}", is_error=True)

    async def _send_request(self, method: str, params: dict[str, Any]) -> Any:
        request_id = str(uuid.uuid4())
        msg = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }
        future: asyncio.Future[Any] = asyncio.get_event_loop().create_future()
        self._pending[request_id] = future

        if self._writer_raw:
            data = json.dumps(msg) + "\n"
            self._writer_raw.write(data.encode())
            await self._writer_raw.drain()

        return await asyncio.wait_for(future, timeout=30)

    async def _send_notification(self, method: str, params: dict[str, Any]) -> None:
        msg = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        if self._writer_raw:
            data = json.dumps(msg) + "\n"
            self._writer_raw.write(data.encode())
            await self._writer_raw.drain()

    async def _read_loop(self) -> None:
        try:
            while self._reader:
                line = await self._reader.readline()
                if not line:
                    break
                try:
                    msg = json.loads(line)
                    msg_id = msg.get("id")
                    if msg_id and msg_id in self._pending:
                        if "error" in msg:
                            self._pending[msg_id].set_exception(
                                RuntimeError(msg["error"].get("message", "MCP error"))
                            )
                        else:
                            self._pending[msg_id].set_result(msg.get("result", {}))
                        del self._pending[msg_id]
                except json.JSONDecodeError:
                    continue
        except asyncio.CancelledError:
            pass


class MCPClient:
    """Manages multiple MCP server connections and registers their tools."""

    def __init__(self, config_path: Path = MCP_CONFIG_PATH) -> None:
        self._config_path = config_path
        self._servers: dict[str, MCPServerConnection] = {}

    async def load_and_start(self, registry: ToolRegistry) -> None:
        """Load MCP config and start all servers."""
        if not self._config_path.exists():
            logger.info("No MCP config found at %s", self._config_path)
            return

        try:
            config = json.loads(self._config_path.read_text())
        except Exception as e:
            logger.error("Failed to load MCP config: %s", e)
            return

        servers = config.get("mcpServers", {})
        for name, server_config in servers.items():
            command = server_config.get("command", "")
            args = server_config.get("args", [])
            env = server_config.get("env")

            conn = MCPServerConnection(name, command, args, env)
            try:
                await conn.start()
                self._servers[name] = conn

                # Discover and register tools
                tools = await conn.list_tools()
                for tool_def in tools:
                    tool_name = f"mcp__{name}__{tool_def['name']}"
                    mcp_tool = MCPTool(
                        name=tool_name,
                        description=tool_def.get("description", ""),
                        parameters=tool_def.get("inputSchema", {"type": "object", "properties": {}}),
                        server=conn,
                    )
                    registry.register(mcp_tool)
                    logger.info("Registered MCP tool: %s", tool_name)
            except Exception as e:
                logger.error("Failed to start MCP server %s: %s", name, e)

    async def stop_all(self) -> None:
        """Stop all MCP server connections."""
        for conn in self._servers.values():
            await conn.stop()
        self._servers.clear()
