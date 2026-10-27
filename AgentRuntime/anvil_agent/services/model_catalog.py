"""Supported model catalog and recommendation engine."""

from __future__ import annotations

from pydantic import BaseModel


MAX_LOADED_CONTEXT = 32768


class ModelCatalogEntry(BaseModel):
    """A local GGUF model that llama.cpp can run."""

    id: str
    name: str
    provider: str
    parameters: str
    min_ram_gb: int
    description: str
    best_for: str
    supports_tools: bool
    context_window: int
    hf_repo: str  # Hugging Face repo holding the GGUF files
    quant: str = "Q4_K_M"  # preferred quantization; the closest available one is used if the repo lacks it

    @property
    def loaded_context(self) -> int:
        """Context length llama-server is started with: the model's maximum, capped to keep KV-cache memory sane."""
        return min(self.context_window, MAX_LOADED_CONTEXT)


MODEL_CATALOG: list[ModelCatalogEntry] = [
    # Gemma 4 family (newest, multimodal: text + image + audio)
    ModelCatalogEntry(
        id="gemma4:e2b",
        name="Gemma 4 E2B",
        provider="google",
        parameters="2.3B effective",
        min_ram_gb=4,
        description="Smallest default — downloads on first use, multimodal",
        best_for="Quick tasks, runs on any Mac",
        supports_tools=True,
        context_window=131072,
        hf_repo="ggml-org/gemma-4-E2B-it-GGUF",
        quant="Q4_0",  # ggml-org publishes Q4_0 only
    ),
    ModelCatalogEntry(
        id="gemma4:e4b",
        name="Gemma 4 E4B",
        provider="google",
        parameters="4B effective",
        min_ram_gb=6,
        description="Stronger multimodal model (text + image + audio)",
        best_for="Balanced quality and speed",
        supports_tools=True,
        context_window=131072,
        hf_repo="ggml-org/gemma-4-E4B-it-GGUF",
        quant="Q4_0",  # ggml-org publishes Q4_0 only
    ),
    ModelCatalogEntry(
        id="gemma4:26b",
        name="Gemma 4 26B A4B",
        provider="google",
        parameters="26B MoE (4B active)",
        min_ram_gb=18,
        description="High-quality multimodal reasoning",
        best_for="Complex tasks, M3/M4 Pro+",
        supports_tools=True,
        context_window=262144,
        hf_repo="ggml-org/gemma-4-26B-A4B-it-GGUF",
        quant="Q4_0",  # ggml-org publishes Q4_0 only
    ),
    # Nous Research Hermes (hybrid reasoning, <tool_call> function calling)
    ModelCatalogEntry(
        id="hermes3:8b",
        name="Hermes 3 8B",
        provider="nousresearch",
        parameters="8B",
        min_ram_gb=6,
        description="Nous Research Hermes 3 (Llama 3.1 base), official GGUF build",
        best_for="Agentic tool use on 8GB Macs",
        supports_tools=True,
        context_window=131072,
        hf_repo="NousResearch/Hermes-3-Llama-3.1-8B-GGUF",
    ),
    ModelCatalogEntry(
        id="hermes4.3:36b",
        name="Hermes 4.3 36B",
        provider="nousresearch",
        parameters="36B",
        min_ram_gb=28,
        description="Nous Hermes 4.3 (Seed-OSS 36B base), hybrid reasoning + tool use; Q4_K_M via Hugging Face GGUF",
        best_for="Top local agent quality, 32GB+ Macs",
        supports_tools=True,
        context_window=65536,
        hf_repo="bartowski/NousResearch_Hermes-4.3-36B-GGUF",
    ),
    # Other models
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
        hf_repo="Qwen/Qwen3-8B-GGUF",
    ),
    ModelCatalogEntry(
        id="llama4-scout",
        name="Llama 4 Scout",
        provider="meta",
        parameters="17B active (109B MoE)",
        min_ram_gb=67,
        description="Meta's mixture-of-experts model",
        best_for="Complex reasoning tasks",
        supports_tools=True,
        context_window=131072,
        hf_repo="unsloth/Llama-4-Scout-17B-16E-Instruct-GGUF",
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
        hf_repo="bartowski/mistralai_Mistral-Small-3.2-24B-Instruct-2506-GGUF",
    ),
    ModelCatalogEntry(
        id="qwen3:32b",
        name="Qwen 3 32B",
        provider="alibaba",
        parameters="32B",
        min_ram_gb=21,
        description="Alibaba's large model for heavy tasks",
        best_for="Complex tasks, M3/M4 Pro+",
        supports_tools=True,
        context_window=32768,
        hf_repo="Qwen/Qwen3-32B-GGUF",
    ),
]


# Default local model: the one suggested first (downloaded on demand, not shipped inside the app)
BUNDLED_MODEL_ID = "gemma4:e2b"


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
            "id": "claude-opus-5-5",
            "name": "Claude Opus 5.5",
            "provider": "anthropic",
            "description": "Most capable Claude model for complex tasks",
            "context_window": 200000,
            "supports_tools": True,
        },
        {
            "id": "claude-sonnet-5-5",
            "name": "Claude Sonnet 5.5",
            "provider": "anthropic",
            "description": "Balanced performance and speed",
            "context_window": 200000,
            "supports_tools": True,
        },
        {
            "id": "claude-haiku-5-5",
            "name": "Claude Haiku 5.5",
            "provider": "anthropic",
            "description": "Fastest Claude model for simple tasks",
            "context_window": 200000,
            "supports_tools": True,
        },
    ]


def lookup_context_window(model: str | None) -> int | None:
    """Context window (tokens) in effect for a catalog or cloud model id; None if unknown."""
    if not model:
        return None
    for entry in MODEL_CATALOG:
        if model == entry.id:
            return entry.loaded_context
    for cloud in get_cloud_models():
        if cloud["id"] == model:
            return cloud["context_window"]
    return None
