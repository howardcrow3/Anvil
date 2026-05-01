"""Main entry point for the Anvil agent runtime."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
import tempfile
from pathlib import Path
from typing import Any

from rich.logging import RichHandler

from anvil_agent.agent_loop import AgentLoop, SYSTEM_PROMPT
from anvil_agent.hooks.engine import HooksEngine, HookEvent
from anvil_agent.ipc.server import IPCServer
from anvil_agent.mcp.client import MCPClient
from anvil_agent.memory.manager import MemoryManager
from anvil_agent.models.claude_provider import ClaudeProvider
from anvil_agent.models.openai_provider import OpenAIProvider
from anvil_agent.models.router import ModelRouter
from anvil_agent.models.types import ChatMessage
from anvil_agent.session.manager import SessionManager
from anvil_agent.teams.manager import TeamManager
from anvil_agent.tools import create_default_registry

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Anvil AI Agent Runtime")
    parser.add_argument(
        "--socket-path",
        default=tempfile.mktemp(prefix="anvil_", suffix=".sock"),
        help="Unix socket path for IPC",
    )
    parser.add_argument(
        "--project-dir",
        default=".",
        help="Project working directory",
    )
    parser.add_argument(
        "--model",
        default="claude-sonnet-4-20250514",
        help="Model name to use",
    )
    parser.add_argument(
        "--provider",
        default="claude",
        choices=["claude", "openai", "ollama"],
        help="Model provider",
    )
    parser.add_argument(
        "--openai-base-url",
        default=None,
        help="Base URL for OpenAI-compatible API",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return parser.parse_args()


class AnvilRuntime:
    """Top-level runtime that wires everything together."""

    def __init__(self, args: argparse.Namespace) -> None:
        self._args = args
        self._project_dir = Path(args.project_dir).resolve()

        # Core components
        self._router = ModelRouter()
        self._tool_registry = create_default_registry()
        self._session_manager = SessionManager()
        self._memory_manager = MemoryManager(self._project_dir)
        self._hooks_engine = HooksEngine()
        self._mcp_client = MCPClient()
        self._team_manager = TeamManager()
        self._ipc = IPCServer(args.socket_path)

        # State
        self._current_session: str | None = None
        self._agent_loop: AgentLoop | None = None
        self._messages: list[ChatMessage] = []

    async def start(self) -> None:
        """Initialize and start the runtime."""
        # Set up model provider
        self._setup_provider()

        # Load memory context
        memory_context = self._memory_manager.load_context()
        system_prompt = SYSTEM_PROMPT
        if memory_context:
            system_prompt += f"\n\n{memory_context}"

        # Create agent loop
        self._agent_loop = AgentLoop(
            provider=self._router.active,
            tool_registry=self._tool_registry,
            system_prompt=system_prompt,
        )

        # Start MCP servers
        await self._mcp_client.load_and_start(self._tool_registry)

        # Register IPC methods
        self._register_ipc_methods()

        # Start IPC server
        await self._ipc.start()

        # Run hooks
        await self._hooks_engine.run(HookEvent.SESSION_START, {})

        logger.info("Anvil runtime started (socket: %s)", self._args.socket_path)

    async def stop(self) -> None:
        """Gracefully shut down the runtime."""
        await self._hooks_engine.run(HookEvent.SESSION_END, {})
        await self._mcp_client.stop_all()
        await self._team_manager.stop_all()
        await self._ipc.stop()
        logger.info("Anvil runtime stopped")

    def _setup_provider(self) -> None:
        match self._args.provider:
            case "claude":
                provider = ClaudeProvider(model=self._args.model)
                self._router.register("claude", provider)
            case "openai":
                provider = OpenAIProvider(
                    model=self._args.model,
                    base_url=self._args.openai_base_url,
                )
                self._router.register("openai", provider)
            case "ollama":
                provider = OpenAIProvider(
                    model=self._args.model,
                    base_url="http://localhost:11434/v1",
                    supports_tool_use=False,
                )
                self._router.register("ollama", provider)

    def _register_ipc_methods(self) -> None:
        self._ipc.register_method("chat.send", self._handle_chat_send)
        self._ipc.register_method("chat.cancel", self._handle_chat_cancel)
        self._ipc.register_method("session.create", self._handle_session_create)
        self._ipc.register_method("session.resume", self._handle_session_resume)
        self._ipc.register_method("session.list", self._handle_session_list)
        self._ipc.register_method("model.list", self._handle_model_list)
        self._ipc.register_method("model.select", self._handle_model_select)
        self._ipc.register_method("team.create", self._handle_team_create)
        self._ipc.register_method("team.status", self._handle_team_status)
        self._ipc.register_method("settings.get", self._handle_settings_get)
        self._ipc.register_method("settings.set", self._handle_settings_set)

    async def _handle_chat_send(
        self, params: dict[str, Any], writer: Any
    ) -> dict[str, Any]:
        message = params.get("message", "")
        if not message:
            return {"error": "No message provided"}

        user_msg = ChatMessage(role="user", content=message)
        self._messages.append(user_msg)

        if self._current_session:
            self._session_manager.append_message(self._current_session, user_msg)
            if len(self._messages) == 1:
                self._session_manager.auto_name(self._current_session, message)

        # Run pre-tool hooks
        await self._hooks_engine.run(HookEvent.PRE_TOOL_USE, {"message": message})

        # Stream agent response
        full_response = ""
        assert self._agent_loop is not None
        async for event in self._agent_loop.run(self._messages):
            await self._ipc.send_notification(writer, "chat.event", event)
            if event.get("type") == "text_delta":
                full_response += event.get("text", "")

        # Save assistant response
        if full_response:
            assistant_msg = ChatMessage(role="assistant", content=full_response)
            self._messages.append(assistant_msg)
            if self._current_session:
                self._session_manager.append_message(self._current_session, assistant_msg)

        return {"status": "ok"}

    async def _handle_chat_cancel(
        self, params: dict[str, Any], writer: Any
    ) -> dict[str, Any]:
        if self._agent_loop:
            self._agent_loop.cancel()
        return {"status": "cancelled"}

    async def _handle_session_create(
        self, params: dict[str, Any], writer: Any
    ) -> dict[str, Any]:
        name = params.get("name", "")
        session_id = self._session_manager.create(name)
        self._current_session = session_id
        self._messages = []
        return {"session_id": session_id}

    async def _handle_session_resume(
        self, params: dict[str, Any], writer: Any
    ) -> dict[str, Any]:
        session_id = params.get("session_id", "")
        messages = self._session_manager.load_messages(session_id)
        self._current_session = session_id
        self._messages = messages
        return {"session_id": session_id, "message_count": len(messages)}

    async def _handle_session_list(
        self, params: dict[str, Any], writer: Any
    ) -> list[dict[str, Any]]:
        return self._session_manager.list_sessions()

    async def _handle_model_list(
        self, params: dict[str, Any], writer: Any
    ) -> list[dict[str, Any]]:
        return self._router.list_models()

    async def _handle_model_select(
        self, params: dict[str, Any], writer: Any
    ) -> dict[str, Any]:
        name = params.get("name", "")
        try:
            self._router.select(name)
            return {"status": "ok", "active": name}
        except ValueError as e:
            return {"error": str(e)}

    async def _handle_team_create(
        self, params: dict[str, Any], writer: Any
    ) -> dict[str, Any]:
        name = params.get("name", "team")
        members = params.get("members", [])
        team_id = await self._team_manager.create_team(name, members)
        return {"team_id": team_id}

    async def _handle_team_status(
        self, params: dict[str, Any], writer: Any
    ) -> dict[str, Any]:
        team_id = params.get("team_id", "")
        return await self._team_manager.get_status(team_id)

    async def _handle_settings_get(
        self, params: dict[str, Any], writer: Any
    ) -> dict[str, Any]:
        # Stub - settings would come from a config file
        return {"provider": self._args.provider, "model": self._args.model}

    async def _handle_settings_set(
        self, params: dict[str, Any], writer: Any
    ) -> dict[str, Any]:
        # Stub - would persist settings
        return {"status": "ok"}


async def async_main() -> None:
    args = parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(message)s",
        handlers=[RichHandler(rich_tracebacks=True)],
    )

    runtime = AnvilRuntime(args)
    loop = asyncio.get_running_loop()

    # Handle signals for graceful shutdown
    shutdown_event = asyncio.Event()

    def signal_handler() -> None:
        shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    await runtime.start()

    # Print socket path for the Swift app to connect
    print(f"SOCKET:{args.socket_path}", flush=True)

    await shutdown_event.wait()
    await runtime.stop()


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
