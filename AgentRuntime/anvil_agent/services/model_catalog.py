"""Supported model catalog and recommendation engine."""

from __future__ import annotations

from pydantic import BaseModel


class ModelCatalogEntry(BaseModel):
    """A model available in the Ollama catalog."""

    id: str
    name: str
    provider: str
    parameters: str
    min_ram_gb: int
    description: str
    best_for: str
    supports_tools: bool
    context_window: int
    ollama_tag: str


MODEL_CATALOG: list[ModelCatalogEntry] = [
    ModelCatalogEntry(
        id="gemma3:4b",
        name="Gemma 3 4B",
        provider="google",
        parameters="4B",
        min_ram_gb=4,
        description="Google's efficient small model",
        best_for="Fast responses, simple tasks",
        supports_tools=True,
        context_window=8192,
        ollama_tag="gemma3:4b",
    ),
    ModelCatalogEntry(
        id="gemma3:12b",
        name="Gemma 3 12B",
        provider="google",
        parameters="12B",
        min_ram_gb=10,
        description="Google's capable mid-size model",
        best_for="Good all-around performance",
        supports_tools=True,
        context_window=8192,
        ollama_tag="gemma3:12b",
    ),
    ModelCatalogEntry(
        id="llama4-scout",
        name="Llama 4 Scout",
        provider="meta",
        parameters="17B active (109B MoE)",
        min_ram_gb=12,
        description="Meta's mixture-of-experts model",
        best_for="Complex reasoning tasks",
        supports_tools=True,
        context_window=131072,
        ollama_tag="llama4:scout",
    ),
    ModelCatalogEntry(
        id="mistral-small",
        name="Mistral Small 3.2",
        provider="mistral",
        parameters="24B",
        min_ram_gb=16,
        description="Mistral's strong coding model",
        best_for="Code generation and review",
        supports_tools=True,
        context_window=32768,
        ollama_tag="mistral-small:24b",
    ),
    ModelCatalogEntry(
        id="phi4",
        name="Phi-4",
        provider="microsoft",
        parameters="14B",
        min_ram_gb=10,
        description="Microsoft's efficient reasoning model",
        best_for="Efficient reasoning, math",
        supports_tools=True,
        context_window=16384,
        ollama_tag="phi4:14b",
    ),
    ModelCatalogEntry(
        id="qwen3:8b",
        name="Qwen 3 8B",
        provider="alibaba",
        parameters="8B",
        min_ram_gb=6,
        description="Alibaba's multilingual model",
        best_for="Multilingual tasks, coding",
        supports_tools=True,
        context_window=32768,
        ollama_tag="qwen3:8b",
    ),
    ModelCatalogEntry(
        id="qwen3:32b",
        name="Qwen 3 32B",
        provider="alibaba",
        parameters="32B",
        min_ram_gb=20,
        description="Alibaba's large model for heavy tasks",
        best_for="Complex tasks, M3/M4 Pro+",
        supports_tools=True,
        context_window=32768,
        ollama_tag="qwen3:32b",
    ),
]


def get_recommended_models(available_ram_gb: int) -> list[ModelCatalogEntry]:
    """Return models that fit within the given RAM budget, sorted by size."""
    return sorted(
        [m for m in MODEL_CATALOG if m.min_ram_gb <= available_ram_gb],
        key=lambda m: m.min_ram_gb,
    )


def get_model_by_id(model_id: str) -> ModelCatalogEntry | None:
    """Look up a catalog entry by its ID."""
    for model in MODEL_CATALOG:
        if model.id == model_id:
            return model
    return None


def get_cloud_models() -> list[dict]:
    """Return the list of Claude cloud models available via Anthropic API."""
    return [
        {
            "id": "claude-opus-4-6",
            "name": "Claude Opus 4.6",
            "provider": "anthropic",
            "description": "Most capable Claude model for complex tasks",
            "context_window": 200000,
            "supports_tools": True,
        },
        {
            "id": "claude-sonnet-4-6",
            "name": "Claude Sonnet 4.6",
            "provider": "anthropic",
            "description": "Balanced performance and speed",
            "context_window": 200000,
            "supports_tools": True,
        },
        {
            "id": "claude-haiku-4-5-20251001",
            "name": "Claude Haiku 4.5",
            "provider": "anthropic",
            "description": "Fastest Claude model for simple tasks",
            "context_window": 200000,
            "supports_tools": True,
        },
    ]
