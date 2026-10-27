"""OpenAI-compatible model provider (works with llama-server, LM Studio, vLLM, etc.)."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import openai

from anvil_agent.models.router import ModelProvider
from anvil_agent.models.types import ChatChunk, ChatMessage, ToolCallDelta


class OpenAIProvider(ModelProvider):
    """Model provider for OpenAI-compatible APIs."""

    def __init__(
        self,
        model: str = "gpt-4o",
        api_key: str | None = None,
        base_url: str | None = None,
        supports_tool_use: bool = True,
    ) -> None:
        self.model_name = model
        self.supports_tool_use = supports_tool_use
        self._client = openai.AsyncOpenAI(
            api_key=api_key or "not-needed",
            base_url=base_url,
        )

    async def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
        stream: bool = True,
    ) -> AsyncIterator[ChatChunk]:
        oai_messages = self._convert_messages(messages)
        kwargs: dict[str, Any] = {
            "model": self.model_name,
            "messages": oai_messages,
            "stream": stream,
        }
        if tools and self.supports_tool_use:
            kwargs["tools"] = self._convert_tools(tools)

        if stream:
            async for chunk in self._stream_response(**kwargs):
                yield chunk
        else:
            response = await self._client.chat.completions.create(**kwargs)
            choice = response.choices[0]
            if choice.message.content:
                yield ChatChunk(delta_text=choice.message.content)
            if choice.message.tool_calls:
                for tc in choice.message.tool_calls:
                    yield ChatChunk(
                        tool_call_delta=ToolCallDelta(
                            id=tc.id,
                            name=tc.function.name,
                            arguments_delta=tc.function.arguments,
                        )
                    )
            yield ChatChunk(finish_reason=choice.finish_reason or "stop")

    async def _stream_response(self, **kwargs: Any) -> AsyncIterator[ChatChunk]:
        stream = await self._client.chat.completions.create(**kwargs)
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            finish = chunk.choices[0].finish_reason

            if delta.content:
                yield ChatChunk(delta_text=delta.content)

            if delta.tool_calls:
                for tc in delta.tool_calls:
                    yield ChatChunk(
                        tool_call_delta=ToolCallDelta(
                            id=tc.id,
                            name=tc.function.name if tc.function and tc.function.name else None,
                            arguments_delta=tc.function.arguments if tc.function and tc.function.arguments else "",
                        )
                    )

            if finish:
                yield ChatChunk(finish_reason=finish)

    async def health_check(self) -> bool:
        try:
            await self._client.models.list()
            return True
        except Exception:
            return False

    def _convert_messages(self, messages: list[ChatMessage]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for msg in messages:
            if msg.role == "tool":
                result.append(
                    {
                        "role": "tool",
                        "tool_call_id": msg.tool_call_id,
                        "content": msg.content,
                    }
                )
            elif msg.tool_calls:
                oai_msg: dict[str, Any] = {
                    "role": "assistant",
                    "content": msg.content or None,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments),
                            },
                        }
                        for tc in msg.tool_calls
                    ],
                }
                result.append(oai_msg)
            else:
                result.append({"role": msg.role, "content": msg.content})
        return result

    def _convert_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool.get("parameters", {"type": "object", "properties": {}}),
                },
            }
            for tool in tools
        ]
