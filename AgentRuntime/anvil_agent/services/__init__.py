"""Anvil services: llama.cpp lifecycle, model catalog, system info, endpoints."""

from anvil_agent.services.model_catalog import (
    MODEL_CATALOG,
    ModelCatalogEntry,
    get_cloud_models,
    get_model_by_id,
    get_recommended_models,
)
from anvil_agent.services.llama_cpp_service import LlamaCppError, LlamaCppService
from anvil_agent.services.system_info import SystemInfo, get_system_info

__all__ = [
    "MODEL_CATALOG",
    "ModelCatalogEntry",
    "LlamaCppError",
    "LlamaCppService",
    "SystemInfo",
    "get_cloud_models",
    "get_model_by_id",
    "get_recommended_models",
    "get_system_info",
]
