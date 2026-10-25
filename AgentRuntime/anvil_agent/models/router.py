"""Model provider abstraction and router."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from anvil_agent.models.types import ChatChunk, ChatMessage


class ModelProvider(ABC):
    """Abstract base class for model providers."""

    model_name: str
    supports_tool_use: bool = True

    @abstractmethod
    async def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
        stream: bool = True,
    ) -> AsyncIterator[ChatChunk]:
        """Send messages to the model and get streaming response chunks."""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the provider is reachable."""
        ...


class ModelRouter:
    """Routes requests to the appropriate model provider.

    Providers are registered by model_id (e.g. "claude-sonnet-5-5").
    Each entry also tracks its provider_type ("cloud", "local", or "custom").
    """

    def __init__(self) -> None:
        self._providers: dict[str, ModelProvider] = {}
        self._provider_types: dict[str, str] = {}
        self._active: str | None = None

    def register(
        self,
        model_id: str,
        provider: ModelProvider,
        provider_type: str = "cloud",
    ) -> None:
        """Register a provider keyed by model_id with a provider_type tag."""
        self._providers[model_id] = provider
        self._provider_types[model_id] = provider_type
        if self._active is None:
            self._active = model_id

    def select(self, model_id: str) -> None:
        if model_id not in self._providers:
            raise ValueError(f"Unknown model: {model_id}")
        self._active = model_id

    @property
    def active(self) -> ModelProvider:
        if self._active is None:
            raise RuntimeError("No model provider configured")
        return self._providers[self._active]

    @property
    def active_model_id(self) -> str | None:
        return self._active

    def has(self, model_id: str) -> bool:
        return model_id in self._providers

    def list_models(self) -> list[dict[str, Any]]:
        return [
            {
                "id": model_id,
                "name": p.model_name,
                "provider": self._provider_types.get(model_id, "cloud"),
                "active": model_id == self._active,
                "supports_tool_use": p.supports_tool_use,
            }
            for model_id, p in self._providers.items()
        ]
