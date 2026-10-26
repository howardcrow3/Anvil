"""MCP (Model Context Protocol) client built on the official ``mcp`` SDK.

Servers are configured in ``~/.anvil/mcp-servers.json`` (Claude Desktop / Claude Code style)::

    {
      "mcpServers": {
        "files":  {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]},
        "remote": {"url": "https://example.com/mcp", "headers": {"Authorization": "Bearer ${TOKEN}"}},
        "legacy": {"url": "https://example.com/sse", "type": "sse"}
      }
    }

Transport is chosen per server: ``command`` -> stdio, ``url`` -> streamable HTTP (or SSE when
``"type": "sse"`` or the URL path ends in ``/sse``). Optional keys: ``enabled`` (default true),
``timeout`` (seconds per tool call, default 60), ``connect_timeout`` (default 30), ``env``,
``cwd``, ``headers``. ``${VAR}`` references in ``env``/``headers``/``url`` are expanded.

Each server runs in its own long-lived task that owns the SDK session (the SDK's transports use
anyio task groups, which must be entered and exited from the same task). A server that fails to
connect is logged and skipped; it never prevents the others from starting.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from mcp import Client, StdioServerParameters, types
from mcp.client.sse import sse_client
from mcp.client.stdio import get_default_environment
from mcp.client.streamable_http import streamable_http_client

from anvil_agent.models.types import ToolResult
from anvil_agent.tools.base import Tool
from anvil_agent.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

MCP_CONFIG_PATH = Path.home() / ".anvil" / "mcp-servers.json"

DEFAULT_CALL_TIMEOUT = 60.0
DEFAULT_CONNECT_TIMEOUT = 30.0
MAX_TOOL_NAME_LEN = 64  # Anthropic / OpenAI tool-name limit

_INVALID_NAME_CHARS = re.compile(r"[^a-zA-Z0-9_-]")


def _sanitize(part: str) -> str:
    return _INVALID_NAME_CHARS.sub("_", part)


def make_tool_name(server: str, tool: str) -> str:
    """Model-visible name ``mcp__<server>__<tool>``, restricted to ``[a-zA-Z0-9_-]`` and 64 chars."""
    full = f"mcp__{_sanitize(server)}__{_sanitize(tool)}"
    if len(full) <= MAX_TOOL_NAME_LEN:
        return full
    digest = hashlib.sha1(f"{server}\0{tool}".encode()).hexdigest()[:8]
    return f"{full[: MAX_TOOL_NAME_LEN - 9]}_{digest}"


def _expand(value: Any) -> Any:
    """Expand ``${VAR}`` / ``$VAR`` in strings, recursing into dicts and lists."""
    if isinstance(value, str):
        return os.path.expandvars(value)
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v) for v in value]
    return value


def format_call_result(result: types.CallToolResult) -> str:
    """Flatten an MCP tool result into text for the model.

    Text and embedded text resources pass through; binary content (images, audio, blobs) is
    summarised with a placeholder because the tool-result channel is text-only.
    """
    parts: list[str] = []
    for block in result.content or []:
        if isinstance(block, types.TextContent):
            parts.append(block.text)
        elif isinstance(block, types.ImageContent):
            parts.append(f"[image: {block.mime_type}, {len(block.data) * 3 // 4} bytes omitted]")
        elif isinstance(block, types.AudioContent):
            parts.append(f"[audio: {block.mime_type}, {len(block.data) * 3 // 4} bytes omitted]")
        elif isinstance(block, types.EmbeddedResource):
            res = block.resource
            if isinstance(res, types.TextResourceContents):
                parts.append(res.text)
            else:
                parts.append(f"[binary resource: {res.uri}]")
        else:
            uri = getattr(block, "uri", None)
            parts.append(f"[resource link: {uri}]" if uri else json.dumps(block.model_dump(mode="json")))
    if not parts and result.structured_content is not None:
        parts.append(json.dumps(result.structured_content))
    return "\n".join(parts)


class MCPTool(Tool):
    """A tool backed by an MCP server."""

    requires_approval = True
    defer = True

    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        server: "MCPServerConnection",
        remote_name: str,
    ) -> None:
        self.name = name  # model-visible, prefixed
        self.description = description
        self.parameters = parameters
        self._server = server
        self._remote_name = remote_name  # the server's own name for the tool

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return await self._server.call_tool(self._remote_name, arguments)


class MCPServerConnection:
    """One MCP server, over stdio, streamable HTTP or SSE, via the official SDK."""

    def __init__(self, name: str, config: dict[str, Any]) -> None:
        self.name = name
        self._config = config
        self._call_timeout = float(config.get("timeout", DEFAULT_CALL_TIMEOUT))
        self._connect_timeout = float(config.get("connect_timeout", DEFAULT_CONNECT_TIMEOUT))
        self._client: Client | None = None
        self._runner: asyncio.Task[None] | None = None
        self._ready = asyncio.Event()
        self._stop = asyncio.Event()
        self._error: BaseException | None = None

    # -- lifecycle ------------------------------------------------------------

    @property
    def transport_kind(self) -> str:
        if self._config.get("command"):
            return "stdio"
        url = str(self._config.get("url", ""))
        kind = str(self._config.get("type", "")).lower()
        if kind == "sse" or (not kind and url.rstrip("/").endswith("/sse")):
            return "sse"
        return "http"

    def _build_transport(self) -> Any:
        cfg = self._config
        kind = self.transport_kind
        if kind == "stdio":
            # Start from the SDK's small safe set (PATH, HOME, ...), not the whole environment: stdio servers
            # are third-party code and must not inherit ANVIL_WS_TOKEN or API keys. Only what the user
            # configured under "env" is added.
            env = {**get_default_environment(), **_expand(cfg.get("env") or {})}
            return StdioServerParameters(
                command=cfg["command"],
                args=[str(a) for a in _expand(cfg.get("args") or [])],
                env=env,
                cwd=cfg.get("cwd"),
            )
        url = _expand(cfg.get("url", ""))
        if not url:
            raise ValueError("server needs either 'command' or 'url'")
        headers = _expand(cfg.get("headers") or {})
        if kind == "sse":
            return sse_client(url, headers=headers or None)
        if headers:
            import httpx2

            return streamable_http_client(url, http_client=httpx2.AsyncClient(headers=headers, follow_redirects=True))
        return streamable_http_client(url)

    async def _run(self) -> None:
        try:
            async with Client(self._build_transport(), read_timeout_seconds=self._call_timeout) as client:
                self._client = client
                self._ready.set()
                await self._stop.wait()
        except BaseException as e:  # noqa: BLE001 - surfaced to start() / logged
            self._error = e
            if not isinstance(e, asyncio.CancelledError):
                logger.error("MCP server %s stopped: %s", self.name, e)
            if not self._ready.is_set():
                self._ready.set()
            if isinstance(e, asyncio.CancelledError):
                raise
        finally:
            self._client = None

    async def start(self) -> None:
        """Connect and initialize. Raises on failure or timeout."""
        self._runner = asyncio.create_task(self._run(), name=f"mcp-{self.name}")
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=self._connect_timeout)
        except asyncio.TimeoutError:
            await self.stop()
            raise TimeoutError(f"timed out after {self._connect_timeout:.0f}s connecting to MCP server {self.name!r}")
        if self._client is None:
            err = self._error
            await self.stop()
            raise RuntimeError(f"failed to connect to MCP server {self.name!r}: {err!r}")

    async def stop(self) -> None:
        self._stop.set()
        runner, self._runner = self._runner, None
        if runner is not None:
            try:
                await asyncio.wait_for(runner, timeout=10)
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                runner.cancel()
                try:
                    await runner
                except BaseException:  # noqa: BLE001
                    pass

    @property
    def connected(self) -> bool:
        return self._client is not None

    # -- operations -----------------------------------------------------------

    async def list_tools(self) -> list[types.Tool]:
        """All tools the server exposes (follows pagination)."""
        assert self._client is not None, "not connected"
        tools: list[types.Tool] = []
        cursor: str | None = None
        while True:
            page = await self._client.list_tools(cursor=cursor)
            tools.extend(page.tools)
            cursor = page.next_cursor
            if not cursor:
                return tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Call ``name`` (the server's own tool name, not the prefixed one)."""
        if self._client is None:
            return ToolResult(id="", content=f"MCP server {self.name!r} is not connected", is_error=True)
        try:
            result = await asyncio.wait_for(
                self._client.call_tool(name, arguments), timeout=self._call_timeout + 5
            )
        except asyncio.TimeoutError:
            return ToolResult(id="", content=f"MCP error: {name} timed out after {self._call_timeout:.0f}s", is_error=True)
        except Exception as e:  # noqa: BLE001
            return ToolResult(id="", content=f"MCP error: {e}", is_error=True)
        return ToolResult(id="", content=format_call_result(result), is_error=bool(result.is_error))


_KNOWN_KEYS = {"command", "args", "env", "cwd", "url", "headers", "type", "enabled", "timeout", "connect_timeout"}


def server_to_entry(server: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    """Convert the UI/IPC shape (``transport`` + flat fields) to a config-file entry.

    Keys the UI doesn't know about (from a hand-edited file) are preserved from ``existing``.
    """
    entry: dict[str, Any] = {k: v for k, v in (existing or {}).items() if k not in _KNOWN_KEYS}
    transport = server.get("transport", "stdio")
    if transport == "stdio":
        entry["command"] = server.get("command", "")
        if server.get("args"):
            entry["args"] = [str(a) for a in server["args"]]
        if server.get("env"):
            entry["env"] = dict(server["env"])
        if server.get("cwd"):
            entry["cwd"] = server["cwd"]
    else:
        entry["type"] = "sse" if transport == "sse" else "http"
        entry["url"] = server.get("url", "")
        if server.get("headers"):
            entry["headers"] = dict(server["headers"])
    if not server.get("enabled", True):
        entry["enabled"] = False
    if server.get("timeout"):
        entry["timeout"] = float(server["timeout"])
    if existing and existing.get("connect_timeout"):
        entry["connect_timeout"] = existing["connect_timeout"]
    return entry


def entry_to_server(name: str, entry: dict[str, Any]) -> dict[str, Any]:
    """Convert a config-file entry to the UI/IPC shape."""
    probe = MCPServerConnection(name, entry)
    return {
        "name": name,
        "transport": probe.transport_kind,
        "enabled": bool(entry.get("enabled", True)),
        "command": entry.get("command", ""),
        "args": [str(a) for a in entry.get("args") or []],
        "cwd": entry.get("cwd") or "",
        "env": {str(k): str(v) for k, v in (entry.get("env") or {}).items()},
        "url": entry.get("url", ""),
        "headers": {str(k): str(v) for k, v in (entry.get("headers") or {}).items()},
        "timeout": float(entry.get("timeout", DEFAULT_CALL_TIMEOUT)),
    }


def validate_server(server: dict[str, Any]) -> str | None:
    """Return a human-readable problem with a UI-shape server dict, or ``None`` if it's usable."""
    name = str(server.get("name", "")).strip()
    if not name:
        return "Server name is required"
    transport = server.get("transport", "stdio")
    if transport == "stdio":
        if not str(server.get("command", "")).strip():
            return f"{name}: command is required for a stdio server"
    elif transport in ("http", "sse"):
        url = str(server.get("url", "")).strip()
        if not re.match(r"^https?://\S+$", url):
            return f"{name}: a valid http(s) URL is required"
    else:
        return f"{name}: unknown transport {transport!r}"
    return None


class MCPClient:
    """Manages multiple MCP server connections and registers their tools."""

    def __init__(self, config_path: Path = MCP_CONFIG_PATH) -> None:
        self._config_path = config_path
        self._servers: dict[str, MCPServerConnection] = {}
        self._registered: list[str] = []
        self._tools_by_server: dict[str, list[dict[str, str]]] = {}
        self.failures: dict[str, str] = {}

    # -- config file ----------------------------------------------------------

    def read_entries(self) -> dict[str, dict[str, Any]]:
        """The raw ``mcpServers`` mapping from the config file ({} if missing or unreadable)."""
        if not self._config_path.exists():
            return {}
        try:
            config = json.loads(self._config_path.read_text())
        except Exception as e:  # noqa: BLE001
            logger.error("Failed to load MCP config: %s", e)
            return {}
        return {n: c for n, c in (config.get("mcpServers") or {}).items() if isinstance(c, dict)}

    def write_servers(self, servers: list[dict[str, Any]]) -> None:
        """Persist UI-shape servers to the config file (atomic, owner-only permissions).

        Raises ``ValueError`` on an invalid or duplicate server; nothing is written in that case.
        """
        existing = self.read_entries()
        entries: dict[str, Any] = {}
        for server in servers:
            problem = validate_server(server)
            if problem:
                raise ValueError(problem)
            name = str(server["name"]).strip()
            if name in entries:
                raise ValueError(f"Duplicate server name {name!r}")
            entries[name] = server_to_entry(server, existing.get(name))
        # Keep other top-level keys a hand-edited file may carry.
        try:
            config = json.loads(self._config_path.read_text()) if self._config_path.exists() else {}
        except Exception:  # noqa: BLE001
            config = {}
        config["mcpServers"] = entries
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self._config_path.parent, prefix=".mcp-servers.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(config, f, indent=2)
            os.chmod(tmp, 0o600)  # headers/env may hold tokens
            os.replace(tmp, self._config_path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    # -- lifecycle ------------------------------------------------------------

    async def load_and_start(self, registry: ToolRegistry) -> None:
        """Load MCP config, connect to all enabled servers concurrently, register their tools."""
        if not self._config_path.exists():
            logger.info("No MCP config found at %s", self._config_path)
            return
        entries = {n: c for n, c in self.read_entries().items() if c.get("enabled", True)}
        results = await asyncio.gather(*(self._start_one(n, c, registry) for n, c in entries.items()))
        started = sum(1 for ok in results if ok)
        logger.info("MCP: %d/%d servers connected, %d tools registered", started, len(entries), len(self._registered))

    async def reload(self, registry: ToolRegistry) -> None:
        """Stop everything and start again from the config file (picks up UI edits)."""
        await self.stop_all(registry)
        self.failures.clear()
        await self.load_and_start(registry)

    async def _start_one(self, name: str, cfg: dict[str, Any], registry: ToolRegistry) -> bool:
        conn = MCPServerConnection(name, cfg)
        try:
            await conn.start()
            tools = await conn.list_tools()
        except Exception as e:  # noqa: BLE001
            logger.error("Failed to start MCP server %s: %s", name, e)
            self.failures[name] = str(e)
            await conn.stop()
            return False
        self._servers[name] = conn
        self._tools_by_server[name] = []
        for tool_def in tools:
            tool_name = make_tool_name(name, tool_def.name)
            registry.register(
                MCPTool(
                    name=tool_name,
                    description=tool_def.description or tool_def.title or "",
                    parameters=tool_def.input_schema or {"type": "object", "properties": {}},
                    server=conn,
                    remote_name=tool_def.name,
                )
            )
            self._registered.append(tool_name)
            self._tools_by_server[name].append({"name": tool_name, "description": tool_def.description or ""})
            logger.info("Registered MCP tool: %s (%s)", tool_name, conn.transport_kind)
        return True

    async def test_server(self, server: dict[str, Any]) -> dict[str, Any]:
        """Try a UI-shape server without registering anything. Returns ``{ok, tools|error}``."""
        problem = validate_server(server)
        if problem:
            return {"ok": False, "error": problem}
        conn = MCPServerConnection(str(server["name"]).strip(), server_to_entry(server))
        try:
            await conn.start()
            tools = await conn.list_tools()
            return {"ok": True, "tools": [{"name": t.name, "description": t.description or ""} for t in tools]}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}
        finally:
            await conn.stop()

    # -- status ---------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Connection summary."""
        return {
            "connected": {n: {"transport": c.transport_kind, "alive": c.connected} for n, c in self._servers.items()},
            "failed": dict(self.failures),
        }

    def list_servers(self) -> list[dict[str, Any]]:
        """Every configured server in UI shape, with live status and tool names."""
        out = []
        for name, entry in self.read_entries().items():
            server = entry_to_server(name, entry)
            conn = self._servers.get(name)
            if not server["enabled"]:
                state = "disabled"
            elif conn is not None and conn.connected:
                state = "connected"
            elif name in self.failures:
                state = "failed"
            else:
                state = "stopped"  # configured but not (yet) started, e.g. edited since last reload
            server.update(
                status=state,
                error=self.failures.get(name, ""),
                tools=self._tools_by_server.get(name, []),
            )
            out.append(server)
        return out

    async def stop_all(self, registry: ToolRegistry | None = None) -> None:
        """Stop all MCP server connections (and unregister their tools if a registry is given)."""
        await asyncio.gather(*(c.stop() for c in self._servers.values()), return_exceptions=True)
        if registry is not None:
            for name in self._registered:
                registry.unregister(name)
        self._servers.clear()
        self._registered.clear()
        self._tools_by_server.clear()
