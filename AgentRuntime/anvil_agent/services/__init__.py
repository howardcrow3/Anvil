"""Anvil services: Ollama lifecycle, model catalog, system info, endpoints."""

from anvil_agent.services.model_catalog import (
    MODEL_CATALOG,
    ModelCatalogEntry,
    get_cloud_models,
    get_model_by_id,
    get_recommended_models,
)
from anvil_agent.services.ollama_service import OllamaService
from anvil_agent.services.system_info import SystemInfo, get_system_info

__all__ = [
    "MODEL_CATALOG",
    "ModelCatalogEntry",
    "OllamaService",
    "SystemInfo",
    "get_cloud_models",
    "get_model_by_id",
    "get_recommended_models",
    "get_system_info",
]
