"""Provider for local GGUF models served by llama.cpp's ``llama-server``."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from anvil_agent.models.openai_provider import OpenAIProvider
from anvil_agent.models.router import ModelProvider
from anvil_agent.models.types import ChatChunk, ChatMessage
from anvil_agent.services.llama_cpp_service import LlamaCppService
from anvil_agent.services.model_catalog import ModelCatalogEntry


class LlamaCppProvider(ModelProvider):
    """Starts (or reuses) the model's llama-server on first use, then talks to it as an OpenAI endpoint.

    Nothing is launched when the provider is registered, so the app starts fast and an unused local
    model costs no memory.
    """

    def __init__(self, entry: ModelCatalogEntry, service: LlamaCppService) -> None:
        self.model_name = entry.id
        self.supports_tool_use = entry.supports_tools
        self._entry = entry
        self._service = service
        self._inner: tuple[tuple[str, str], OpenAIProvider] | None = None

    async def _provider(self) -> OpenAIProvider:
        endpoint = await self._service.ensure_running(self._entry)  # raises LlamaCppError with a readable message
        if self._inner is None or self._inner[0] != endpoint:
            base_url, key = endpoint
            self._inner = (endpoint, OpenAIProvider(
                model=self._entry.id, api_key=key, base_url=f"{base_url}/v1", supports_tool_use=self._entry.supports_tools
            ))
        return self._inner[1]

    async def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
        stream: bool = True,
    ) -> AsyncIterator[ChatChunk]:
        provider = await self._provider()
        async for chunk in provider.chat(messages, tools=tools, stream=stream):
            yield chunk

    async def health_check(self) -> bool:
        return self._service.is_downloaded(self._entry) and self._service.resolve_binary() is not None
