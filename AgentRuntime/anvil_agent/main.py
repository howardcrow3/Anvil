"""Main entry point for the Anvil agent runtime."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
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
from anvil_agent.services.model_catalog import get_cloud_models, MODEL_CATALOG
from anvil_agent.services.ollama_service import OllamaService
from anvil_agent.session.manager import SessionManager
from anvil_agent.settings import SettingsManager
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
        default=None,
        help="Model name to use (overrides saved default)",
    )
    parser.add_argument(
        "--provider",
        default=None,
        choices=["claude", "openai", "ollama"],
        help="Model provider (overrides saved default)",
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

        # Settings (load first so other components can use saved values)
        self._settings = SettingsManager()

        # Core components
        self._router = ModelRouter()
        self._tool_registry = create_default_registry()
        self._session_manager = SessionManager()
        self._memory_manager = MemoryManager(self._project_dir)
        self._hooks_engine = HooksEngine()
        self._mcp_client = MCPClient()
        self._team_manager = TeamManager()
        self._ollama = OllamaService()
        self._ipc = IPCServer(args.socket_path)

        # State
        self._current_session: str | None = None
        self._agent_loop: AgentLoop | None = None
        self._messages: list[ChatMessage] = []

    async def start(self) -> None:
        """Initialize and start the runtime."""
        # Register all providers
        self._setup_providers()

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
            working_directory=str(self._project_dir),
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

    # ── Provider Setup ────────────────────────────────────────────

    def _setup_providers(self) -> None:
        """Register all available providers: cloud models, local, and custom endpoints."""
        api_key = self._settings.get_api_key()

        # Determine the model to select as active
        active_model = (
            self._args.model
            or self._settings.get("default_model")
            or "claude-sonnet-4-20250514"
        )

        # Register cloud (Claude) models
        if api_key:
            for cloud_model in get_cloud_models():
                model_id = cloud_model["id"]
                provider = ClaudeProvider(model=model_id, api_key=api_key)
                self._router.register(model_id, provider, provider_type="cloud")

        # Register custom endpoints from settings
        for ep in self._settings.get("endpoints") or []:
            ep_name = ep.get("name", "")
            ep_model = ep.get("default_model", ep_name)
            ep_url = ep.get("base_url", "")
            ep_key = ep.get("api_key", "")
            if ep_url:
                provider = OpenAIProvider(
                    model=ep_model,
                    api_key=ep_key or None,
                    base_url=ep_url,
                )
                model_id = f"custom:{ep_name}" if ep_name else ep_model
                self._router.register(model_id, provider, provider_type="custom")

        # CLI --provider override for backwards compatibility
        if self._args.provider == "openai":
            model = self._args.model or "gpt-4o"
            provider = OpenAIProvider(
                model=model,
                base_url=self._args.openai_base_url,
            )
            self._router.register(model, provider, provider_type="custom")
            active_model = model
        elif self._args.provider == "ollama":
            model = self._args.model or "gemma3:4b"
            provider = OpenAIProvider(
                model=model,
                base_url=f"http://localhost:{self._settings.get('ollama_port') or 11434}/v1",
                supports_tool_use=False,
            )
            self._router.register(model, provider, provider_type="local")
            active_model = model

        # Select the active model
        if self._router.has(active_model):
            self._router.select(active_model)

    def _create_provider_for_model(
        self, model_id: str
    ) -> tuple[str, Any] | None:
        """Dynamically create a provider for a model_id.

        Returns (provider_type, provider) or None if unrecognized.
        """
        api_key = self._settings.get_api_key()

        # Cloud Claude models
        for cloud_model in get_cloud_models():
            if cloud_model["id"] == model_id:
                if not api_key:
                    return None
                return ("cloud", ClaudeProvider(model=model_id, api_key=api_key))

        # Ollama catalog models
        for cat_model in MODEL_CATALOG:
            if cat_model.id == model_id:
                port = self._settings.get("ollama_port") or 11434
                return (
                    "local",
                    OpenAIProvider(
                        model=cat_model.ollama_tag,
                        base_url=f"http://localhost:{port}/v1",
                        supports_tool_use=cat_model.supports_tools,
                    ),
                )

        return None

    # ── IPC Registration ──────────────────────────────────────────

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

    # ── Chat Handlers ─────────────────────────────────────────────

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

    # ── Session Handlers ──────────────────────────────────────────

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

    # ── Model Handlers ────────────────────────────────────────────

    async def _handle_model_list(
        self, params: dict[str, Any], writer: Any
    ) -> list[dict[str, Any]]:
        """Return merged catalog of cloud, local, and custom models."""
        models: list[dict[str, Any]] = []
        registered_ids = {m["id"] for m in self._router.list_models()}
        active_id = self._router.active_model_id

        # Cloud models from catalog
        for cloud in get_cloud_models():
            models.append({
                "id": cloud["id"],
                "name": cloud["name"],
                "provider": "cloud",
                "status": "available" if cloud["id"] in registered_ids else "needs_key",
                "active": cloud["id"] == active_id,
            })

        # Local models from Ollama catalog
        for cat in MODEL_CATALOG:
            models.append({
                "id": cat.id,
                "name": cat.name,
                "provider": "local",
                "status": "available" if cat.id in registered_ids else "downloadable",
                "size": cat.parameters,
                "active": cat.id == active_id,
            })

        # Custom endpoints
        for ep in self._settings.get("endpoints") or []:
            ep_name = ep.get("name", "")
            model_id = f"custom:{ep_name}" if ep_name else ep.get("default_model", "")
            models.append({
                "id": model_id,
                "name": ep_name or model_id,
                "provider": "custom",
                "status": "available" if model_id in registered_ids else "configured",
                "active": model_id == active_id,
            })

        return models

    async def _handle_model_select(
        self, params: dict[str, Any], writer: Any
    ) -> dict[str, Any]:
        model_id = params.get("model_id", "") or params.get("name", "")
        if not model_id:
            return {"error": "No model_id provided"}

        # If not yet registered, try to create it dynamically
        if not self._router.has(model_id):
            result = self._create_provider_for_model(model_id)
            if result is None:
                return {"error": f"Unknown model: {model_id}"}
            provider_type, provider = result
            self._router.register(model_id, provider, provider_type=provider_type)

        try:
            self._router.select(model_id)
            # Re-create agent loop with the new provider
            if self._agent_loop is not None:
                self._agent_loop = AgentLoop(
                    provider=self._router.active,
                    tool_registry=self._tool_registry,
                    system_prompt=self._agent_loop._system_prompt,
                    working_directory=str(self._project_dir),
                )
            return {"status": "ok", "active": model_id}
        except ValueError as e:
            return {"error": str(e)}

    # ── Team Handlers ─────────────────────────────────────────────

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

    # ── Settings Handlers ─────────────────────────────────────────

    async def _handle_settings_get(
        self, params: dict[str, Any], writer: Any
    ) -> dict[str, Any]:
        key = params.get("key")
        if key:
            value = self._settings.get(key)
            return {"key": key, "value": value}
        return self._settings.get_all()

    async def _handle_settings_set(
        self, params: dict[str, Any], writer: Any
    ) -> dict[str, Any]:
        key = params.get("key", "")
        value = params.get("value")
        if not key:
            return {"error": "No key provided"}
        try:
            self._settings.set(key, value)
            return {"status": "ok", "key": key, "value": value}
        except KeyError as e:
            return {"error": str(e)}


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
