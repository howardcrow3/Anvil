"""Main entry point for the Anvil agent runtime."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

from rich.logging import RichHandler

from anvil_agent.agent_loop import AgentLoop, SYSTEM_PROMPT
from anvil_agent.gateway.config import GatewayConfig, load_gateway_config, save_gateway_config
from anvil_agent.gateway.server import GatewayServer
from anvil_agent.git.detector import GitDetector
from anvil_agent.git.service import GitService
from anvil_agent.hooks.engine import HooksEngine, HookEvent
from anvil_agent.ipc.server import IPCServer
from anvil_agent.mcp.client import MCPClient
from anvil_agent.memory.manager import MemoryManager
from anvil_agent.memory.nudger import MemoryNudger
from anvil_agent.memory.user_model import UserModelManager
from anvil_agent.models.claude_provider import ClaudeProvider
from anvil_agent.models.openai_provider import OpenAIProvider
from anvil_agent.models.router import ModelRouter
from anvil_agent.models.types import ChatMessage
from anvil_agent.permissions import PermissionManager, PermissionMode
from anvil_agent.planning.manager import PlanManager
from anvil_agent.services.model_catalog import (
    get_cloud_models, get_model_by_id, MODEL_CATALOG, BUNDLED_MODEL_ID,
)
from anvil_agent.services.ollama_service import OllamaService
from anvil_agent.session.manager import SessionManager
from anvil_agent.session.search import SessionSearchDB
from anvil_agent.settings import SettingsManager
from anvil_agent.skills.creator import SkillCreator
from anvil_agent.skills.executor import SkillExecutor
from anvil_agent.skills.hub import SkillsHub
from anvil_agent.skills.improver import SkillImprover
from anvil_agent.skills.loader import SkillLoader
from anvil_agent.projects.manager import ProjectManager
from anvil_agent.teams.manager import TeamManager
from anvil_agent.teams.orchestrator import TeamOrchestrator
from anvil_agent.system.info import get_system_info, recommend_models
from anvil_agent.system.monitor import PerformanceMonitor
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

        # Session search DB (initialized async in start())
        self._search_db = SessionSearchDB()

        # Core components
        self._router = ModelRouter()
        self._tool_registry = create_default_registry(search_db=self._search_db)
        self._session_manager = SessionManager(search_db=self._search_db)
        self._memory_manager = MemoryManager(self._project_dir)
        self._user_model = UserModelManager()
        self._nudger = MemoryNudger()
        self._hooks_engine = HooksEngine()
        self._plan_manager = PlanManager()
        self._skill_loader = SkillLoader(self._project_dir)
        self._skill_loader.load_project_skills()
        self._skill_loader.load_user_skills()
        self._skill_creator = SkillCreator()
        self._skill_improver = SkillImprover()
        self._skills_hub = SkillsHub(self._skill_loader)
        self._skill_executor = SkillExecutor(
            self._skill_loader, self._session_manager, self._settings,
            improver=self._skill_improver,
        )
        self._mcp_client = MCPClient()
        self._team_manager = TeamManager()
        self._project_manager = ProjectManager()
        self._team_orchestrator = TeamOrchestrator(
            self._team_manager, project_dir=self._project_dir
        )
        self._ollama = OllamaService()
        self._perf_monitor = PerformanceMonitor()
        self._ipc = IPCServer(args.socket_path)

        # Permissions
        perm_mode_str = self._settings.get("permission_mode") or "ask"
        try:
            perm_mode = PermissionMode(perm_mode_str)
        except ValueError:
            perm_mode = PermissionMode.ASK
        self._permission_manager = PermissionManager(mode=perm_mode)
        self._permission_manager.set_overrides(
            allow_list=self._settings.get("tool_allow_list"),
            deny_list=self._settings.get("tool_deny_list"),
        )

        # Gateway
        self._gateway: GatewayServer | None = None
        self._gateway_config: GatewayConfig | None = None
        try:
            gw_config = load_gateway_config()
            # Only initialize if at least one platform is configured
            has_platform = any(
                getattr(gw_config, p) is not None and getattr(gw_config, p).enabled
                for p in ("telegram", "discord", "slack", "webhook")
                if getattr(gw_config, p) is not None
            )
            if has_platform:
                self._gateway_config = gw_config
        except Exception:
            pass

        # State
        self._current_session: str | None = None
        self._agent_loop: AgentLoop | None = None
        self._messages: list[ChatMessage] = []
        self._git_service: GitService | None = None

    async def start(self) -> None:
        """Initialize and start the runtime."""
        # Initialize session search DB
        await self._search_db.initialize()

        # Ensure Ollama is running before registering providers
        if not await self._ollama.is_running():
            started = await self._ollama.start()
            if started:
                logger.info("Ollama started on port %d", self._ollama.port)
            else:
                logger.warning("Failed to start Ollama — local models will be unavailable")

        # Register all providers
        self._setup_providers()

        # Load memory context
        memory_context = self._memory_manager.load_context()
        system_prompt = SYSTEM_PROMPT
        if memory_context:
            system_prompt += f"\n\n{memory_context}"

        # Inject user profile
        user_prompt = self._user_model.get_system_prompt_addition()
        if user_prompt:
            system_prompt += f"\n\n{user_prompt}"

        # Store system prompt for deferred agent loop creation
        self._system_prompt = system_prompt

        # Create agent loop if a provider is available
        if self._router.active_model_id is not None:
            self._agent_loop = AgentLoop(
                provider=self._router.active,
                tool_registry=self._tool_registry,
                system_prompt=system_prompt,
                working_directory=str(self._project_dir),
                permission_manager=self._permission_manager,
                nudger=self._nudger,
                skill_creator=self._skill_creator,
            )
        else:
            logger.warning("No model provider configured — agent loop deferred until a model is selected")

        # Detect git repository
        if await GitDetector.is_git_repo(self._project_dir):
            repo_root = await GitDetector.get_repo_root(self._project_dir)
            if repo_root:
                self._git_service = GitService(repo_root)
                logger.info("Git repository detected at %s", repo_root)

        # Load hooks from config files
        self._hooks_engine.load_from_files(project_dir=self._project_dir)

        # Start MCP servers
        await self._mcp_client.load_and_start(self._tool_registry)

        # Wire IPC into team manager for broadcasting
        self._team_manager.set_ipc(self._ipc)

        # Register IPC methods
        self._register_ipc_methods()

        # Start IPC server
        await self._ipc.start()

        # Signal socket path immediately so Swift app can connect
        # while we continue with non-essential setup (gateway, hooks)
        print(f"SOCKET:{self._args.socket_path}", flush=True)

        # Start gateway if configured
        if self._gateway_config:
            def _gateway_loop_factory() -> AgentLoop:
                return AgentLoop(
                    provider=self._router.active,
                    tool_registry=self._tool_registry,
                    system_prompt=SYSTEM_PROMPT,
                    working_directory=str(self._project_dir),
                )

            self._gateway = GatewayServer(
                config=self._gateway_config,
                agent_loop_factory=_gateway_loop_factory,
                session_manager=self._session_manager,
                tool_registry=self._tool_registry,
            )
            await self._gateway.start()
            logger.info("Gateway started with configured adapters")

        # Run hooks
        await self._hooks_engine.run(HookEvent.SESSION_START, {})

        logger.info("Anvil runtime started (socket: %s)", self._args.socket_path)

    async def stop(self) -> None:
        """Gracefully shut down the runtime."""
        # Update user model from conversation
        if self._messages:
            await self._user_model.update_from_conversation(self._messages)

        await self._hooks_engine.run(HookEvent.SESSION_END, {})
        if self._gateway:
            await self._gateway.stop()
        await self._mcp_client.stop_all()
        await self._team_manager.stop_all()
        await self._search_db.close()
        await self._ollama.stop()
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
            model = self._args.model or "gemma4:e2b"
            catalog_entry = get_model_by_id(model)
            ollama_tag = catalog_entry.ollama_tag if catalog_entry else model
            tool_support = catalog_entry.supports_tools if catalog_entry else False
            provider = OpenAIProvider(
                model=ollama_tag,
                base_url=f"http://localhost:{self._settings.get('ollama_port') or 11434}/v1",
                supports_tool_use=tool_support,
            )
            self._router.register(model, provider, provider_type="local")
            active_model = model

        # Always register the bundled local model as a fallback
        bundled_entry = get_model_by_id(BUNDLED_MODEL_ID)
        if bundled_entry and not self._router.has(BUNDLED_MODEL_ID):
            port = self._settings.get("ollama_port") or 11434
            bundled_provider = OpenAIProvider(
                model=bundled_entry.ollama_tag,
                base_url=f"http://localhost:{port}/v1",
                supports_tool_use=bundled_entry.supports_tools,
            )
            self._router.register(BUNDLED_MODEL_ID, bundled_provider, provider_type="local")

        # Select the active model — fall back to bundled if preferred isn't available
        if self._router.has(active_model):
            self._router.select(active_model)
        elif not api_key and self._router.has(BUNDLED_MODEL_ID):
            self._router.select(BUNDLED_MODEL_ID)
            logger.info("No API key — using bundled model %s", BUNDLED_MODEL_ID)

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
        self._ipc.register_method("team.spawn", self._handle_team_spawn)
        self._ipc.register_method("team.stop_teammate", self._handle_team_stop_teammate)
        self._ipc.register_method("team.stop_all", self._handle_team_stop_all)
        self._ipc.register_method("team.task.create", self._handle_team_task_create)
        self._ipc.register_method("team.task.update", self._handle_team_task_update)
        self._ipc.register_method("team.task.list", self._handle_team_task_list)
        self._ipc.register_method("team.message.send", self._handle_team_message_send)
        self._ipc.register_method("team.message.read", self._handle_team_message_read)
        self._ipc.register_method("team.teammates", self._handle_team_teammates)
        self._ipc.register_method("team.orchestrate", self._handle_team_orchestrate)
        self._ipc.register_method("team.auto_assign", self._handle_team_auto_assign)
        self._ipc.register_method("team.complete_task", self._handle_team_complete_task)
        self._ipc.register_method("team.progress", self._handle_team_progress)
        self._ipc.register_method("system.info", self._handle_system_info)
        self._ipc.register_method("system.stats", self._handle_system_stats)
        self._ipc.register_method("system.recommend_models", self._handle_recommend_models)
        self._ipc.register_method("settings.get", self._handle_settings_get)
        self._ipc.register_method("settings.set", self._handle_settings_set)
        self._ipc.register_method("planning.start", self._handle_planning_start)
        self._ipc.register_method("planning.stop", self._handle_planning_stop)
        self._ipc.register_method("planning.save", self._handle_planning_save)
        self._ipc.register_method("planning.list", self._handle_planning_list)
        self._ipc.register_method("session.search", self._handle_session_search)
        self._ipc.register_method("skills.list", self._handle_skills_list)
        self._ipc.register_method("skills.create", self._handle_skills_create)
        self._ipc.register_method("skills.import", self._handle_skills_import)
        self._ipc.register_method("skills.toggle", self._handle_skills_toggle)
        self._ipc.register_method("skills.delete", self._handle_skills_delete)
        self._ipc.register_method("skills.browse", self._handle_skills_browse)
        self._ipc.register_method("skills.search", self._handle_skills_search)
        self._ipc.register_method("permission.respond", self._handle_permission_respond)
        self._ipc.register_method("git.status", self._handle_git_status)
        self._ipc.register_method("git.log", self._handle_git_log)
        self._ipc.register_method("git.diff", self._handle_git_diff)
        self._ipc.register_method("gateway.status", self._handle_gateway_status)
        self._ipc.register_method("gateway.start", self._handle_gateway_start)
        self._ipc.register_method("gateway.stop", self._handle_gateway_stop)
        self._ipc.register_method("gateway.config.get", self._handle_gateway_config_get)
        self._ipc.register_method("gateway.config.set", self._handle_gateway_config_set)
        self._ipc.register_method("project.create", self._handle_project_create)
        self._ipc.register_method("project.list", self._handle_project_list)
        self._ipc.register_method("project.get", self._handle_project_get)
        self._ipc.register_method("project.delete", self._handle_project_delete)
        self._ipc.register_method("project.task.create", self._handle_project_task_create)
        self._ipc.register_method("project.task.update", self._handle_project_task_update)
        self._ipc.register_method("project.task.delete", self._handle_project_task_delete)

    # ── Chat Handlers ─────────────────────────────────────────────

    async def _handle_chat_send(
        self, params: dict[str, Any], writer: Any
    ) -> dict[str, Any]:
        message = params.get("message", "")
        if not message:
            return {"error": "No message provided"}

        # Switch session if the client specifies a different one
        requested_session = params.get("session_id", "")
        if requested_session and requested_session != self._current_session:
            # Try to load existing session
            existing_msgs = self._session_manager.load_messages(requested_session)
            if existing_msgs or (self._session_manager._dir / f"{requested_session}.meta.json").exists():
                self._current_session = requested_session
                self._messages = existing_msgs
            else:
                # Session doesn't exist yet (create IPC may not have arrived) — create it
                self._session_manager.create(session_id=requested_session)
                self._current_session = requested_session
                self._messages = []

        # Handle slash commands before entering the agent loop
        if message.startswith("/"):
            result = await self._skill_executor.handle_command(
                message, self._messages
            )
            if result is not None:
                action = result.get("action")
                if action == "toggle_plan_mode":
                    if self._agent_loop:
                        self._agent_loop._planning_mode = not self._agent_loop._planning_mode
                        mode = "planning" if self._agent_loop._planning_mode else "normal"
                        result["text"] = f"Switched to {mode} mode."
                elif action == "resume_last_session":
                    sessions = self._session_manager.list_sessions()
                    if sessions:
                        sid = sessions[0]["id"]
                        msgs = self._session_manager.load_messages(sid)
                        self._current_session = sid
                        self._messages = msgs
                        result["text"] = f"Resumed session ({len(msgs)} messages)."
                    else:
                        result["text"] = "No previous sessions found."
                await self._ipc.send_notification(
                    writer, "chat.event",
                    {"type": "text_delta", "text": result.get("text", "")},
                )
                await self._ipc.send_notification(
                    writer, "chat.event",
                    {"type": "done", "stop_reason": "command"},
                )
                return {"status": "ok"}

        # Fire UserPromptSubmit hook before processing
        allowed, _ = await self._hooks_engine.run(
            HookEvent.USER_PROMPT_SUBMIT, {"message": message}
        )
        if not allowed:
            return {"error": "Message blocked by hook"}

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
        if self._agent_loop is None:
            error_text = (
                "No model is configured. Please set your Anthropic API key in "
                "Settings, or select a local model via the model selector."
            )
            await self._ipc.send_notification(
                writer, "chat.event",
                {"type": "text_delta", "text": error_text},
            )
            await self._ipc.send_notification(
                writer, "chat.event",
                {"type": "done", "stop_reason": "no_provider"},
            )
            return {"status": "ok"}
        async for event in self._agent_loop.run(self._messages):
            if event.get("type") == "skill_creation_check":
                # Log skill creation opportunity (actual creation via skills.create IPC)
                logger.info(
                    "Skill creation candidate: %d tool calls",
                    event.get("tool_call_count", 0),
                )
                continue
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
        # Update user model from previous conversation
        if self._messages:
            await self._user_model.update_from_conversation(self._messages)

        name = params.get("name", "")
        provided_id = params.get("session_id", None)
        session_id = self._session_manager.create(name, session_id=provided_id)
        self._current_session = session_id
        self._messages = []
        self._nudger.reset()
        self._skill_improver.clear()
        return {"session_id": session_id}

    async def _handle_session_resume(
        self, params: dict[str, Any], writer: Any
    ) -> dict[str, Any]:
        session_id = params.get("session_id", "")
        messages = self._session_manager.load_messages(session_id)
        self._current_session = session_id
        self._messages = messages
        # Return messages so the UI can display the conversation history
        msg_list = []
        for m in messages:
            msg_list.append({"role": m.role, "content": m.content or ""})
        return {"session_id": session_id, "message_count": len(messages), "messages": msg_list}

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
            # Create or re-create agent loop with the new provider
            planning = self._agent_loop._planning_mode if self._agent_loop else False
            prompt = self._agent_loop._system_prompt if self._agent_loop else self._system_prompt
            self._agent_loop = AgentLoop(
                provider=self._router.active,
                tool_registry=self._tool_registry,
                system_prompt=prompt,
                working_directory=str(self._project_dir),
                planning_mode=planning,
                permission_manager=self._permission_manager,
                nudger=self._nudger,
                skill_creator=self._skill_creator,
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
        # Also create any tasks specified
        for task_spec in params.get("tasks", []):
            self._team_manager.create_task(
                team_id,
                title=task_spec.get("title", ""),
                description=task_spec.get("description", ""),
                depends_on=task_spec.get("depends_on", []),
            )
        return {"team_id": team_id}

    async def _handle_team_status(
        self, params: dict[str, Any], writer: Any
    ) -> dict[str, Any]:
        team_id = params.get("team_id", "")
        return await self._team_manager.get_status(team_id)

    async def _handle_team_spawn(
        self, params: dict[str, Any], writer: Any
    ) -> dict[str, Any]:
        team_id = params.get("team_id", "")
        name = params.get("name", "")
        role = params.get("role", "general")
        model = params.get("model", "claude-sonnet-4-6")
        provider = params.get("provider", "claude")
        socket_path = f"/tmp/anvil_teammate_{uuid.uuid4().hex[:8]}.sock"
        member_id = await self._team_manager.spawn_teammate(
            team_id, role=role, name=name,
            socket_path=socket_path,
            project_dir=str(self._project_dir),
            model=model, provider=provider,
        )
        return {"member_id": member_id, "socket_path": socket_path}

    async def _handle_team_stop_teammate(
        self, params: dict[str, Any], writer: Any
    ) -> dict[str, Any]:
        member_id = params.get("member_id", "")
        if not member_id:
            return {"error": "No member_id provided"}
        await self._team_manager.stop_teammate(member_id)
        return {"status": "ok"}

    async def _handle_team_stop_all(
        self, params: dict[str, Any], writer: Any
    ) -> dict[str, Any]:
        await self._team_manager.stop_all()
        return {"status": "ok"}

    async def _handle_team_task_create(
        self, params: dict[str, Any], writer: Any
    ) -> dict[str, Any]:
        team_id = params.get("team_id", "")
        title = params.get("title", "")
        description = params.get("description", "")
        depends_on = params.get("depends_on", [])
        task_id = self._team_manager.create_task(
            team_id, title=title, description=description, depends_on=depends_on,
        )
        return {"task_id": task_id}

    async def _handle_team_task_update(
        self, params: dict[str, Any], writer: Any
    ) -> dict[str, Any]:
        task_id = params.get("task_id", "")
        if not task_id:
            return {"error": "No task_id provided"}
        updates = {k: v for k, v in params.items() if k != "task_id"}
        task = self._team_manager.update_task(task_id, **updates)
        if task is None:
            return {"error": "Task not found"}
        return {"task": task}

    async def _handle_team_task_list(
        self, params: dict[str, Any], writer: Any
    ) -> list[dict[str, Any]]:
        team_id = params.get("team_id", "")
        return self._team_manager.list_tasks(team_id)

    async def _handle_team_message_send(
        self, params: dict[str, Any], writer: Any
    ) -> dict[str, Any]:
        team_id = params.get("team_id", "")
        from_agent = params.get("from", "")
        to_agent = params.get("to", "")
        content = params.get("content", "")
        self._team_manager.send_message(team_id, from_agent, to_agent, content)
        return {"status": "ok"}

    async def _handle_team_message_read(
        self, params: dict[str, Any], writer: Any
    ) -> list[dict[str, Any]]:
        team_id = params.get("team_id", "")
        agent_name = params.get("agent_name", "")
        return self._team_manager.read_messages(team_id, agent_name)

    async def _handle_team_teammates(
        self, params: dict[str, Any], writer: Any
    ) -> list[dict[str, Any]]:
        team_id = params.get("team_id", "")
        return self._team_manager.list_teammates(team_id)

    # ── Orchestrator Handlers ──────────────────────────────────────

    async def _handle_team_orchestrate(
        self, params: dict[str, Any], writer: Any
    ) -> dict[str, Any]:
        team_id = await self._team_orchestrator.create_team_from_spec(params)
        return {"team_id": team_id}

    async def _handle_team_auto_assign(
        self, params: dict[str, Any], writer: Any
    ) -> dict[str, Any]:
        team_id = params.get("team_id", "")
        assignments = await self._team_orchestrator.auto_assign_tasks(team_id)
        return {"assignments": assignments}

    async def _handle_team_complete_task(
        self, params: dict[str, Any], writer: Any
    ) -> dict[str, Any]:
        team_id = params.get("team_id", "")
        member_id = params.get("member_id", "")
        task_id = params.get("task_id", "")
        return await self._team_orchestrator.handle_task_completion(
            team_id, member_id, task_id
        )

    async def _handle_team_progress(
        self, params: dict[str, Any], writer: Any
    ) -> dict[str, Any]:
        team_id = params.get("team_id", "")
        return self._team_orchestrator.get_team_progress(team_id)

    # ── System Handlers ──────────────────────────────────────────

    async def _handle_system_info(
        self, params: dict[str, Any], writer: Any
    ) -> dict[str, Any]:
        return get_system_info()

    async def _handle_system_stats(
        self, params: dict[str, Any], writer: Any
    ) -> dict[str, Any]:
        return self._perf_monitor.get_stats()

    async def _handle_recommend_models(
        self, params: dict[str, Any], writer: Any
    ) -> list[dict[str, Any]]:
        info = get_system_info()
        available = info.get("available_ram_gb", 0)
        return recommend_models(available)

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

            # When API key is set, auto-register cloud models and create agent loop
            if key == "api_key" and value:
                for cloud_model in get_cloud_models():
                    model_id = cloud_model["id"]
                    if not self._router.has(model_id):
                        provider = ClaudeProvider(model=model_id, api_key=value)
                        self._router.register(model_id, provider, provider_type="cloud")
                # Select default model and create agent loop if needed
                default_model = (
                    self._settings.get("default_model") or "claude-sonnet-4-20250514"
                )
                if self._router.has(default_model):
                    self._router.select(default_model)
                if self._agent_loop is None and self._router.active_model_id is not None:
                    self._agent_loop = AgentLoop(
                        provider=self._router.active,
                        tool_registry=self._tool_registry,
                        system_prompt=self._system_prompt,
                        working_directory=str(self._project_dir),
                        permission_manager=self._permission_manager,
                        nudger=self._nudger,
                        skill_creator=self._skill_creator,
                    )
                    logger.info("Agent loop created after API key was set")

            return {"status": "ok", "key": key, "value": value}
        except KeyError as e:
            return {"error": str(e)}

    # ── Planning Handlers ─────────────────────────────────────────

    async def _handle_planning_start(
        self, params: dict[str, Any], writer: Any
    ) -> dict[str, Any]:
        if self._agent_loop:
            self._agent_loop._planning_mode = True
        return {"status": "planning"}

    async def _handle_planning_stop(
        self, params: dict[str, Any], writer: Any
    ) -> dict[str, Any]:
        if self._agent_loop:
            self._agent_loop._planning_mode = False
        return {"status": "normal"}

    async def _handle_planning_save(
        self, params: dict[str, Any], writer: Any
    ) -> dict[str, Any]:
        description = params.get("description", "")
        content = params.get("content", "")
        if not description or not content:
            return {"error": "description and content are required"}
        plan_id = self._plan_manager.save_plan(
            description, content, project_dir=self._project_dir
        )
        return {"status": "ok", "plan_id": plan_id}

    async def _handle_planning_list(
        self, params: dict[str, Any], writer: Any
    ) -> list[dict[str, Any]]:
        return self._plan_manager.list_plans(project_dir=self._project_dir)

    # ── Permission Handlers ────────────────────────────────────────

    async def _handle_permission_respond(
        self, params: dict[str, Any], writer: Any
    ) -> dict[str, Any]:
        request_id = params.get("request_id", "")
        approved = params.get("approved", False)
        if not request_id:
            return {"error": "No request_id provided"}
        self._permission_manager.respond(request_id, approved)
        return {"status": "ok"}

    # ── Session Search Handler ────────────────────────────────────

    async def _handle_session_search(
        self, params: dict[str, Any], writer: Any
    ) -> dict[str, Any]:
        query = params.get("query", "")
        limit = params.get("limit", 10)
        if not query:
            return {"error": "No query provided"}
        results = await self._search_db.search(query, limit=limit)
        return {"results": results}

    # ── Skills Handlers ──────────────────────────────────────────

    async def _handle_skills_list(
        self, params: dict[str, Any], writer: Any
    ) -> list[dict[str, Any]]:
        return self._skill_loader.get_all_items()

    async def _handle_skills_create(
        self, params: dict[str, Any], writer: Any
    ) -> dict[str, Any]:
        name = params.get("name", "")
        summary = params.get("summary", "")
        tool_calls = params.get("tool_calls", [])
        if not name:
            return {"error": "No skill name provided"}
        content = await self._skill_creator.create_skill(summary, tool_calls)
        if content:
            self._skill_creator.save_skill(name, content)
            self._skill_loader.load_user_skills()
            return {"status": "ok", "name": name}
        return {"error": "Failed to create skill"}

    async def _handle_skills_import(
        self, params: dict[str, Any], writer: Any
    ) -> dict[str, Any]:
        name = params.get("name", "")
        content = params.get("content", "")
        if not name or not content:
            return {"error": "Both name and content are required"}
        name = name.strip().lower().replace(" ", "-")
        self._skill_creator.save_skill(name, content)
        self._skill_loader.load_user_skills()
        return {"status": "ok", "name": name}

    async def _handle_skills_toggle(
        self, params: dict[str, Any], writer: Any
    ) -> dict[str, Any]:
        skill_id = params.get("id", "")
        enabled = params.get("enabled", True)
        if not skill_id:
            return {"error": "No skill id provided"}
        self._skill_loader.set_enabled(skill_id, enabled)
        return {"status": "ok", "id": skill_id, "enabled": enabled}

    async def _handle_skills_delete(
        self, params: dict[str, Any], writer: Any
    ) -> dict[str, Any]:
        skill_id = params.get("id", "")
        if not skill_id:
            return {"error": "No skill id provided"}
        if self._skill_loader.delete_skill(skill_id):
            return {"status": "ok", "id": skill_id}
        return {"error": "Cannot delete this skill (only user-created skills can be deleted)"}

    async def _handle_skills_browse(
        self, params: dict[str, Any], writer: Any
    ) -> list[dict[str, Any]]:
        return self._skills_hub.browse()

    async def _handle_skills_search(
        self, params: dict[str, Any], writer: Any
    ) -> list[dict[str, Any]]:
        query = params.get("query", "")
        if not query:
            return []
        return self._skills_hub.search(query)

    # ── Gateway Handlers ────────────────────────────────────────

    async def _handle_gateway_status(
        self, params: dict[str, Any], writer: Any
    ) -> dict[str, Any]:
        if not self._gateway:
            return {"running": False, "adapters": {}}
        return self._gateway.get_status()

    async def _handle_gateway_start(
        self, params: dict[str, Any], writer: Any
    ) -> dict[str, Any]:
        config = load_gateway_config()
        if self._gateway:
            await self._gateway.stop()

        def _factory() -> AgentLoop:
            return AgentLoop(
                provider=self._router.active,
                tool_registry=self._tool_registry,
                system_prompt=SYSTEM_PROMPT,
                working_directory=str(self._project_dir),
            )

        self._gateway = GatewayServer(
            config=config,
            agent_loop_factory=_factory,
            session_manager=self._session_manager,
            tool_registry=self._tool_registry,
        )
        self._gateway_config = config
        await self._gateway.start()
        return self._gateway.get_status()

    async def _handle_gateway_stop(
        self, params: dict[str, Any], writer: Any
    ) -> dict[str, Any]:
        if not self._gateway:
            return {"status": "not_running"}
        await self._gateway.stop()
        self._gateway = None
        return {"status": "stopped"}

    async def _handle_gateway_config_get(
        self, params: dict[str, Any], writer: Any
    ) -> dict[str, Any]:
        config = load_gateway_config()
        return config.model_dump()

    async def _handle_gateway_config_set(
        self, params: dict[str, Any], writer: Any
    ) -> dict[str, Any]:
        try:
            config = GatewayConfig(**params)
            save_gateway_config(config)
            return {"status": "ok"}
        except Exception as e:
            return {"error": str(e)}

    # ── Git Handlers ─────────────────────────────────────────────

    async def _handle_git_status(
        self, params: dict[str, Any], writer: Any
    ) -> dict[str, Any]:
        if not self._git_service:
            return {"error": "Not a git repository"}
        return await self._git_service.get_status()

    async def _handle_git_log(
        self, params: dict[str, Any], writer: Any
    ) -> dict[str, Any]:
        if not self._git_service:
            return {"error": "Not a git repository"}
        count = params.get("count", 10)
        return {"commits": await self._git_service.get_log(n=count)}

    async def _handle_git_diff(
        self, params: dict[str, Any], writer: Any
    ) -> dict[str, Any]:
        if not self._git_service:
            return {"error": "Not a git repository"}
        staged = params.get("staged", False)
        return {"diff": await self._git_service.get_diff(staged=staged)}

    # ── Project Handlers ──────────────────────────────────────────

    async def _handle_project_create(
        self, params: dict[str, Any], writer: Any
    ) -> dict[str, Any]:
        name = params.get("name", "")
        if not name:
            return {"error": "name is required"}
        project = self._project_manager.create_project(
            name=name,
            folder_path=params.get("folder_path", ""),
            github_repo=params.get("github_repo", ""),
            project_id=params.get("id"),
        )
        return project

    async def _handle_project_list(
        self, params: dict[str, Any], writer: Any
    ) -> list[dict[str, Any]]:
        return self._project_manager.list_projects()

    async def _handle_project_get(
        self, params: dict[str, Any], writer: Any
    ) -> dict[str, Any]:
        project = self._project_manager.get_project(params.get("id", ""))
        if not project:
            return {"error": "Project not found"}
        return project

    async def _handle_project_delete(
        self, params: dict[str, Any], writer: Any
    ) -> dict[str, Any]:
        if self._project_manager.delete_project(params.get("id", "")):
            return {"status": "ok"}
        return {"error": "Project not found"}

    async def _handle_project_task_create(
        self, params: dict[str, Any], writer: Any
    ) -> dict[str, Any]:
        task = self._project_manager.add_task(
            project_id=params.get("project_id", ""),
            title=params.get("title", ""),
            description=params.get("description", ""),
            task_id=params.get("id"),
        )
        if not task:
            return {"error": "Project not found"}
        return task

    async def _handle_project_task_update(
        self, params: dict[str, Any], writer: Any
    ) -> dict[str, Any]:
        project_id = params.get("project_id", "")
        task_id = params.get("task_id", "")
        status = params.get("status", "not_started")
        ok = self._project_manager.update_task_status(
            project_id=project_id,
            task_id=task_id,
            status=status,
        )
        if ok:
            # Broadcast task status change to all connected clients
            await self._ipc.broadcast_notification("task.status", {
                "project_id": project_id,
                "task_id": task_id,
                "status": status,
            })
        return {"status": "ok"} if ok else {"error": "Task not found"}

    async def _handle_project_task_delete(
        self, params: dict[str, Any], writer: Any
    ) -> dict[str, Any]:
        ok = self._project_manager.delete_task(
            project_id=params.get("project_id", ""),
            task_id=params.get("task_id", ""),
        )
        return {"status": "ok"} if ok else {"error": "Task not found"}


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

    await shutdown_event.wait()
    await runtime.stop()


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
