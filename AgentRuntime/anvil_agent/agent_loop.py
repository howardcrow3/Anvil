"""Core agent loop that orchestrates model interaction and tool execution."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, AsyncIterator

from anvil_agent.models.router import ModelProvider
from anvil_agent.models.types import ChatChunk, ChatMessage, ToolCallDelta, ToolCallRequest, ToolResult
from anvil_agent.permissions import PermissionManager
from anvil_agent.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from anvil_agent.memory.nudger import MemoryNudger
    from anvil_agent.skills.creator import SkillCreator

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 50

BLOCKED_IN_PLANNING = {"write_file", "edit_file", "bash"}

SYSTEM_PROMPT = """You are Anvil, a powerful AI coding assistant running locally on the user's machine.

You have access to tools for reading, writing, and editing files, running shell commands, searching the codebase, and fetching web content. Use these tools to help the user with software engineering tasks.

Guidelines:
- Read files before modifying them
- Use the edit_file tool for targeted changes, write_file for new files
- Use glob and grep to find relevant code
- Use bash for running tests, builds, and other shell commands
- Be concise and direct in your responses
- Ask the user for clarification when requirements are ambiguous"""

PLANNING_SYSTEM_PROMPT = (
    "You are in planning mode. Explore the codebase, analyze requirements, and "
    "create a detailed implementation plan. Do NOT make any changes to files. "
    "Only use read-only tools: read_file, glob, grep, web_search, web_fetch."
)


class AgentLoop:
    """The core agent loop that processes messages and executes tools."""

    def __init__(
        self,
        provider: ModelProvider,
        tool_registry: ToolRegistry,
        system_prompt: str = SYSTEM_PROMPT,
        max_iterations: int = MAX_ITERATIONS,
        working_directory: str | None = None,
        planning_mode: bool = False,
        permission_manager: PermissionManager | None = None,
        nudger: MemoryNudger | None = None,
        skill_creator: SkillCreator | None = None,
    ) -> None:
        self._provider = provider
        self._tools = tool_registry
        self._system_prompt = system_prompt
        self._max_iterations = max_iterations
        self._cancelled = False
        self._working_directory = working_directory
        self._planning_mode = planning_mode
        self._permission_manager = permission_manager
        self._nudger = nudger
        self._skill_creator = skill_creator

    def cancel(self) -> None:
        self._cancelled = True

    async def run(
        self,
        messages: list[ChatMessage],
    ) -> AsyncIterator[dict[str, Any]]:
        """Run the agent loop, yielding events for each step.

        Events:
          {"type": "text_delta", "text": "..."}
          {"type": "tool_call", "id": "...", "name": "...", "arguments": {...}}
          {"type": "tool_result", "id": "...", "content": "...", "is_error": bool}
          {"type": "done", "stop_reason": "..."}
          {"type": "error", "message": "..."}
        """
        self._cancelled = False
        tool_call_count = 0
        last_success = True

        active_prompt = PLANNING_SYSTEM_PROMPT if self._planning_mode else self._system_prompt
        full_messages = [
            ChatMessage(role="system", content=active_prompt),
            *messages,
        ]

        tool_schemas = self._tools.get_all_schemas()

        for iteration in range(self._max_iterations):
            if self._cancelled:
                yield {"type": "done", "stop_reason": "cancelled"}
                return

            # Collect the full response from streaming
            full_text = ""
            tool_calls: list[ToolCallRequest] = []
            tool_call_buffers: dict[str, dict[str, Any]] = {}
            finish_reason = None

            try:
                async for chunk in self._provider.chat(
                    full_messages, tools=tool_schemas if tool_schemas else None
                ):
                    if self._cancelled:
                        yield {"type": "done", "stop_reason": "cancelled"}
                        return

                    if chunk.delta_text:
                        full_text += chunk.delta_text
                        yield {"type": "text_delta", "text": chunk.delta_text}

                    if chunk.tool_call_delta:
                        tc = chunk.tool_call_delta
                        if tc.id and tc.name:
                            tool_call_buffers[tc.id] = {
                                "id": tc.id,
                                "name": tc.name,
                                "arguments_json": "",
                            }
                        if tc.id and tc.arguments_delta:
                            if tc.id in tool_call_buffers:
                                tool_call_buffers[tc.id]["arguments_json"] += tc.arguments_delta
                        elif tc.arguments_delta and tool_call_buffers:
                            last_id = list(tool_call_buffers.keys())[-1]
                            tool_call_buffers[last_id]["arguments_json"] += tc.arguments_delta

                    if chunk.finish_reason:
                        finish_reason = chunk.finish_reason

            except Exception as e:
                logger.exception("Model error")
                yield {"type": "error", "message": str(e)}
                return

            # Parse completed tool calls
            for tc_id, buf in tool_call_buffers.items():
                try:
                    args = json.loads(buf["arguments_json"]) if buf["arguments_json"] else {}
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append(
                    ToolCallRequest(id=buf["id"], name=buf["name"], arguments=args)
                )

            # If no tool calls, we're done
            if not tool_calls:
                # Add assistant message to history
                full_messages.append(ChatMessage(role="assistant", content=full_text))
                # Skill creation check at end of run
                if self._skill_creator and self._skill_creator.should_create_skill(
                    tool_call_count, last_success
                ):
                    yield {"type": "skill_creation_check", "tool_call_count": tool_call_count}
                yield {"type": "done", "stop_reason": finish_reason or "end_turn"}
                return

            # Add assistant message with tool calls
            full_messages.append(
                ChatMessage(role="assistant", content=full_text, tool_calls=tool_calls)
            )

            # Execute each tool call
            for tc in tool_calls:
                yield {
                    "type": "tool_call",
                    "id": tc.id,
                    "name": tc.name,
                    "arguments": tc.arguments,
                }

                # Block write tools in planning mode
                if self._planning_mode and tc.name in BLOCKED_IN_PLANNING:
                    error_content = f"Tool '{tc.name}' is blocked in planning mode"
                    yield {
                        "type": "tool_result",
                        "id": tc.id,
                        "content": error_content,
                        "is_error": True,
                    }
                    full_messages.append(
                        ChatMessage(
                            role="tool",
                            content=error_content,
                            tool_call_id=tc.id,
                        )
                    )
                    continue

                # Permission check
                if self._permission_manager:
                    decision = self._permission_manager.check_sync(tc.name)
                    if decision == "deny":
                        error_content = "Tool use denied by permission policy"
                        yield {
                            "type": "tool_result",
                            "id": tc.id,
                            "content": error_content,
                            "is_error": True,
                        }
                        full_messages.append(
                            ChatMessage(
                                role="tool",
                                content=error_content,
                                tool_call_id=tc.id,
                            )
                        )
                        continue
                    elif decision == "ask":
                        yield {
                            "type": "permission_request",
                            "request_id": tc.id,
                            "tool_name": tc.name,
                            "arguments": tc.arguments,
                        }
                        approved = await self._permission_manager.request_permission(
                            tc.id, tc.name, tc.arguments
                        )
                        if not approved:
                            error_content = "Tool use denied by user"
                            yield {
                                "type": "tool_result",
                                "id": tc.id,
                                "content": error_content,
                                "is_error": True,
                            }
                            full_messages.append(
                                ChatMessage(
                                    role="tool",
                                    content=error_content,
                                    tool_call_id=tc.id,
                                )
                            )
                            continue

                # Inject working_directory for tools that accept it
                if self._working_directory and "working_dir" not in tc.arguments:
                    if tc.name in ("bash", "glob", "grep"):
                        tc.arguments["working_dir"] = self._working_directory

                result = await self._tools.execute(tc)
                tool_call_count += 1
                if result.is_error:
                    last_success = False

                yield {
                    "type": "tool_result",
                    "id": result.id,
                    "content": result.content[:10000],  # Truncate large results
                    "is_error": result.is_error,
                }

                full_messages.append(
                    ChatMessage(
                        role="tool",
                        content=result.content[:10000],
                        tool_call_id=result.id,
                    )
                )

            # Memory nudge check at iteration boundary
            if self._nudger:
                nudge = self._nudger.check_nudge(iteration + 1)
                if nudge:
                    full_messages.append(ChatMessage(role="system", content=nudge))

        # Skill creation check at end of run
        if self._skill_creator and self._skill_creator.should_create_skill(
            tool_call_count, last_success
        ):
            yield {"type": "skill_creation_check", "tool_call_count": tool_call_count}

        yield {"type": "done", "stop_reason": "max_iterations"}
