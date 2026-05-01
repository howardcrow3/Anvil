"""Manage custom OpenAI-compatible endpoints."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

CONFIG_PATH = Path.home() / ".anvil" / "endpoints.json"


class EndpointConfig(BaseModel):
    """Configuration for a custom OpenAI-compatible endpoint."""

    name: str
    base_url: str
    api_key: str = ""
    default_model: str = ""


class EndpointStatus(BaseModel):
    """An endpoint with its reachability status."""

    config: EndpointConfig
    reachable: bool


class EndpointManager:
    """CRUD and health-check manager for custom OpenAI-compatible endpoints."""

    def __init__(self, config_path: Path = CONFIG_PATH) -> None:
        self._path = config_path
        self._endpoints: list[EndpointConfig] = []
        self._load()

    # ── CRUD ───────────────────────────────────────────────────────

    def list(self) -> list[EndpointConfig]:
        """Return all configured endpoints."""
        return list(self._endpoints)

    def get(self, name: str) -> EndpointConfig | None:
        """Get an endpoint by name."""
        for ep in self._endpoints:
            if ep.name == name:
                return ep
        return None

    def add(self, endpoint: EndpointConfig) -> None:
        """Add a new endpoint. Raises ValueError if name already exists."""
        if self.get(endpoint.name) is not None:
            raise ValueError(f"Endpoint '{endpoint.name}' already exists")
        self._endpoints.append(endpoint)
        self._save()

    def update(self, name: str, **kwargs: str) -> EndpointConfig:
        """Update fields on an existing endpoint. Returns updated config."""
        ep = self.get(name)
        if ep is None:
            raise KeyError(f"Endpoint '{name}' not found")

        for field, value in kwargs.items():
            if hasattr(ep, field):
                setattr(ep, field, value)
            else:
                raise ValueError(f"Unknown field: {field}")
        self._save()
        return ep

    def delete(self, name: str) -> bool:
        """Delete an endpoint by name. Returns True if found and deleted."""
        before = len(self._endpoints)
        self._endpoints = [ep for ep in self._endpoints if ep.name != name]
        if len(self._endpoints) < before:
            self._save()
            return True
        return False

    # ── Health ─────────────────────────────────────────────────────

    async def check_health(self, name: str) -> bool:
        """Check if an endpoint is reachable (GET /v1/models or base_url)."""
        ep = self.get(name)
        if ep is None:
            return False

        headers: dict[str, str] = {}
        if ep.api_key:
            headers["Authorization"] = f"Bearer {ep.api_key}"

        async with httpx.AsyncClient(timeout=10.0) as client:
            # Try the OpenAI-compatible models endpoint first
            for path in ("/v1/models", "/models", ""):
                url = ep.base_url.rstrip("/") + path
                try:
                    resp = await client.get(url, headers=headers)
                    if resp.status_code < 500:
                        return True
                except (httpx.HTTPError, Exception):
                    continue
        return False

    async def list_with_status(self) -> list[EndpointStatus]:
        """Return all endpoints with reachability status."""
        results: list[EndpointStatus] = []
        for ep in self._endpoints:
            reachable = await self.check_health(ep.name)
            results.append(EndpointStatus(config=ep, reachable=reachable))
        return results

    # ── Persistence ────────────────────────────────────────────────

    def _load(self) -> None:
        """Load endpoints from disk."""
        if not self._path.exists():
            self._endpoints = []
            return
        try:
            raw = json.loads(self._path.read_text())
            self._endpoints = [EndpointConfig(**e) for e in raw]
        except (json.JSONDecodeError, Exception) as exc:
            logger.warning("Failed to load endpoints config: %s", exc)
            self._endpoints = []

    def _save(self) -> None:
        """Persist endpoints to disk."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = [ep.model_dump() for ep in self._endpoints]
        self._path.write_text(json.dumps(data, indent=2) + "\n")
