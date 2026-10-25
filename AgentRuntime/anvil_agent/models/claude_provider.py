"""Claude model provider via Anthropic SDK."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import anthropic

from anvil_agent.models.router import ModelProvider
from anvil_agent.models.types import ChatChunk, ChatMessage, ToolCallDelta


class ClaudeProvider(ModelProvider):
    """Model provider for Anthropic Claude models."""

    supports_tool_use: bool = True

    def __init__(
        self,
        model: str = "claude-sonnet-5-5",
        api_key: str | None = None,
        max_tokens: int = 8192,
    ) -> None:
        self.model_name = model
        self._max_tokens = max_tokens
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    async def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
        stream: bool = True,
    ) -> AsyncIterator[ChatChunk]:
        claude_messages = self._convert_messages(messages)
        system_prompt = self._extract_system(messages)
        claude_tools = self._convert_tools(tools) if tools else []

        kwargs: dict[str, Any] = {
            "model": self.model_name,
            "max_tokens": self._max_tokens,
            "messages": claude_messages,
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        if claude_tools:
            kwargs["tools"] = claude_tools

        if stream:
            async for chunk in self._stream_response(**kwargs):
                yield chunk
        else:
            response = await self._client.messages.create(**kwargs)
            for block in response.content:
                if block.type == "text":
                    yield ChatChunk(delta_text=block.text)
                elif block.type == "tool_use":
                    yield ChatChunk(
                        tool_call_delta=ToolCallDelta(
                            id=block.id,
                            name=block.name,
                            arguments_delta=json.dumps(block.input),
                        )
                    )
            yield ChatChunk(finish_reason=response.stop_reason or "end_turn")

    async def _stream_response(self, **kwargs: Any) -> AsyncIterator[ChatChunk]:
        current_tool_id: str | None = None
        async with self._client.messages.stream(**kwargs) as stream:
            async for event in stream:
                match event.type:
                    case "content_block_start":
                        if event.content_block.type == "tool_use":
                            current_tool_id = event.content_block.id
                            yield ChatChunk(
                                tool_call_delta=ToolCallDelta(
                                    id=event.content_block.id,
                                    name=event.content_block.name,
                                )
                            )
                    case "content_block_delta":
                        if event.delta.type == "text_delta":
                            yield ChatChunk(delta_text=event.delta.text)
                        elif event.delta.type == "input_json_delta":
                            yield ChatChunk(
                                tool_call_delta=ToolCallDelta(
                                    id=current_tool_id,
                                    arguments_delta=event.delta.partial_json,
                                )
                            )
                    case "content_block_stop":
                        current_tool_id = None
                    case "message_stop":
                        pass

            final = await stream.get_final_message()
            yield ChatChunk(finish_reason=final.stop_reason or "end_turn")

    async def health_check(self) -> bool:
        try:
            await self._client.messages.create(
                model=self.model_name,
                max_tokens=1,
                messages=[{"role": "user", "content": "hi"}],
            )
            return True
        except Exception:
            return False

    def _extract_system(self, messages: list[ChatMessage]) -> str:
        parts = [m.content for m in messages if m.role == "system"]
        return "\n\n".join(parts)

    def _convert_messages(self, messages: list[ChatMessage]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for msg in messages:
            if msg.role == "system":
                continue
            if msg.role == "tool":
                result.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": msg.tool_call_id,
                                "content": msg.content,
                            }
                        ],
                    }
                )
            elif msg.tool_calls:
                content: list[dict[str, Any]] = []
                if msg.content:
                    content.append({"type": "text", "text": msg.content})
                for tc in msg.tool_calls:
                    content.append(
                        {
                            "type": "tool_use",
                            "id": tc.id,
                            "name": tc.name,
                            "input": tc.arguments,
                        }
                    )
                result.append({"role": "assistant", "content": content})
            else:
                result.append({"role": msg.role, "content": msg.content})
        return result

    def _convert_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        claude_tools = []
        for tool in tools:
            claude_tools.append(
                {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "input_schema": tool.get("parameters", {"type": "object", "properties": {}}),
                }
            )
        return claude_tools
