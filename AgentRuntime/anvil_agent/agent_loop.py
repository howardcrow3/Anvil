"""Core agent loop that orchestrates model interaction and tool execution."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, AsyncIterator, Callable

from anvil_agent.budget import IterationBudget
from anvil_agent.compaction import Compactor
from anvil_agent.context import current_agent_id
from anvil_agent.guardrails import GuardConfig, ToolLoopGuard
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
        context_window: int | None = None,
        unattended: bool = False,
        agent_id: str = "main",
        notes_source: Callable[[str], list[str]] | None = None,
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
        self.agent_id = agent_id
        self._notes_source = notes_source
        self._steer_queue: list[str] = []
        # Loop guardrails always warn; unattended runs (gateway, scheduled) also hard-stop.
        self._guard = ToolLoopGuard(GuardConfig(hard_stop=unattended))
        if context_window is None:
            from anvil_agent.services.model_catalog import lookup_context_window

            context_window = lookup_context_window(getattr(provider, "model_name", None))
        self._compactor = Compactor(context_window) if context_window else None

    def cancel(self) -> None:
        self._cancelled = True

    def steer(self, text: str) -> None:
        """Queue a course correction. It is delivered as a user row right after the next tool
        round (assistant(tool_calls) -> tool -> user is legal on every provider), or before the
        run would otherwise finish."""
        if text.strip():
            self._steer_queue.append(text.strip())

    def _drain_steer(self, messages: list[ChatMessage]) -> bool:
        if not self._steer_queue:
            return False
        text, self._steer_queue = "\n".join(self._steer_queue), []
        messages.append(ChatMessage(role="user", content=f"[Steering from user]\n{text}"))
        return True

    async def _summarize(self, prompt: str) -> str:
        """One tool-less model call used by context compaction."""
        text = ""
        async for chunk in self._provider.chat([ChatMessage(role="user", content=prompt)], tools=None):
            text += chunk.delta_text
        return text

    @staticmethod
    def _annotate_last_tool(messages: list[ChatMessage], note: str) -> None:
        """Attach a note to the newest tool result. Mid-run guidance must ride a tool result,
        never a new system/user row, so role alternation and the cached prefix stay intact."""
        if messages and messages[-1].role == "tool":
            messages[-1] = messages[-1].model_copy(update={"content": f"{messages[-1].content}\n\n{note}"})

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
        current_agent_id.set(self.agent_id)
        tool_call_count = 0
        last_success = True

        active_prompt = PLANNING_SYSTEM_PROMPT if self._planning_mode else self._system_prompt
        full_messages = [
            ChatMessage(role="system", content=active_prompt),
            *messages,
        ]

        tool_schemas = self._tools.get_all_schemas()
        self._guard.reset()
        budget = IterationBudget(self._max_iterations)
        iteration = -1
        halt_message: str | None = None

        while budget.consume():
            iteration += 1
            if self._cancelled:
                yield {"type": "done", "stop_reason": "cancelled"}
                return

            # Compact old context before it overflows the model's window.
            if self._compactor and self._compactor.needs_compaction(full_messages):
                compaction = await self._compactor.compact(full_messages, self._summarize)
                if compaction.changed:
                    full_messages = compaction.messages
                    yield {
                        "type": "compaction",
                        "pruned": compaction.pruned,
                        "summarized": compaction.summarized,
                        "tokens_before": compaction.tokens_before,
                        "tokens_after": compaction.tokens_after,
                    }

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
            invalid_args: dict[str, str] = {}
            for tc_id, buf in tool_call_buffers.items():
                try:
                    args = json.loads(buf["arguments_json"]) if buf["arguments_json"] else {}
                    if not isinstance(args, dict):
                        raise ValueError("arguments must be a JSON object")
                except (json.JSONDecodeError, ValueError) as exc:
                    # Do not run the tool with silently empty arguments; tell the model instead.
                    invalid_args[tc_id] = str(exc)
                    args = {}
                tool_calls.append(
                    ToolCallRequest(id=buf["id"], name=buf["name"], arguments=args)
                )

            # If no tool calls, we're done
            if not tool_calls:
                # Add assistant message to history
                full_messages.append(ChatMessage(role="assistant", content=full_text))
                # A steer that arrived mid-turn keeps the run going instead of being dropped.
                if self._drain_steer(full_messages):
                    continue
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
                unwrap = getattr(self._tools, "unwrap", None)
                eff_name, eff_args = unwrap(tc) if unwrap else (tc.name, tc.arguments)
                yield {
                    "type": "tool_call",
                    "id": tc.id,
                    "name": tc.name,
                    "arguments": tc.arguments,
                }

                if halt_message:
                    skipped = "Skipped: the tool loop was halted."
                    yield {"type": "tool_result", "id": tc.id, "content": skipped, "is_error": True}
                    full_messages.append(ChatMessage(role="tool", content=skipped, tool_call_id=tc.id))
                    continue

                if tc.id in invalid_args:
                    bad = (
                        f"Invalid arguments for tool '{tc.name}': {invalid_args[tc.id]}. "
                        "Re-send the call with a valid JSON object of arguments."
                    )
                    yield {"type": "tool_result", "id": tc.id, "content": bad, "is_error": True}
                    full_messages.append(ChatMessage(role="tool", content=bad, tool_call_id=tc.id))
                    continue

                # Block write tools in planning mode
                if self._planning_mode and eff_name in BLOCKED_IN_PLANNING:
                    error_content = f"Tool '{eff_name}' is blocked in planning mode"
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
                    decision = self._permission_manager.check_sync(eff_name)
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
                        req_id = tc.id if self.agent_id == "main" else f"{self.agent_id}:{tc.id}"
                        yield {
                            "type": "permission_request",
                            "request_id": req_id,
                            "tool_name": eff_name,
                            "arguments": eff_args,
                        }
                        approved = await self._permission_manager.request_permission(
                            req_id, eff_name, eff_args
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
                if self._working_directory and "working_dir" not in eff_args:
                    if eff_name in ("bash", "glob", "grep"):
                        eff_args["working_dir"] = self._working_directory

                pre = self._guard.before_call(eff_name, eff_args)
                if not pre.allows_execution:
                    yield {"type": "tool_result", "id": tc.id, "content": pre.message, "is_error": True}
                    full_messages.append(ChatMessage(role="tool", content=pre.message, tool_call_id=tc.id))
                    continue

                result = await self._tools.execute(tc)
                tool_call_count += 1
                if result.is_error:
                    last_success = False

                content = result.content[:10000]  # Truncate large results
                post = self._guard.after_call(eff_name, eff_args, content, result.is_error)
                if post.message:
                    content = f"{content}\n\n{post.message}"
                if post.should_halt:
                    halt_message = post.message

                yield {
                    "type": "tool_result",
                    "id": result.id,
                    "content": content,
                    "is_error": result.is_error,
                }

                full_messages.append(
                    ChatMessage(
                        role="tool",
                        content=content,
                        tool_call_id=result.id,
                    )
                )

            if halt_message:
                yield {"type": "done", "stop_reason": "tool_loop_halt", "message": halt_message}
                return

            # Memory nudge check at iteration boundary
            if self._nudger:
                nudge = self._nudger.check_nudge(iteration + 1)
                if nudge:
                    self._annotate_last_tool(full_messages, f"[note] {nudge}")

            # Finished background subagents report through the newest tool result.
            if self._notes_source:
                for note in self._notes_source(self.agent_id):
                    self._annotate_last_tool(full_messages, note)

            self._drain_steer(full_messages)

        # Budget exhausted: one tool-less grace call so the user gets a wrap-up, not a silent stop.
        if not self._cancelled:
            self._annotate_last_tool(
                full_messages,
                "[note] Iteration budget exhausted. Reply with a short summary of what is done and what remains. Do not call tools.",
            )
            try:
                async for chunk in self._provider.chat(full_messages, tools=None):
                    if chunk.delta_text:
                        yield {"type": "text_delta", "text": chunk.delta_text}
            except Exception as e:  # noqa: BLE001
                logger.exception("Grace call failed")
                yield {"type": "error", "message": str(e)}

        # Skill creation check at end of run
        if self._skill_creator and self._skill_creator.should_create_skill(
            tool_call_count, last_success
        ):
            yield {"type": "skill_creation_check", "tool_call_count": tool_call_count}

        yield {"type": "done", "stop_reason": "max_iterations"}
