"""Settings persistence for Anvil agent runtime."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

ANVIL_DIR = Path.home() / ".anvil"
CONFIG_PATH = ANVIL_DIR / "config.json"


class AnvilSettings(BaseModel):
    """Persisted settings for the Anvil agent runtime."""

    api_key: str = ""
    default_model: str = "claude-sonnet-4-20250514"
    default_provider: str = "claude"
    permission_mode: str = "ask"
    ollama_port: int = 11434
    endpoints: list[dict[str, Any]] = Field(default_factory=list)
    mcp_servers: list[dict[str, Any]] = Field(default_factory=list)


class SettingsManager:
    """Load, save, and query ~/.anvil/config.json."""

    def __init__(self, config_path: Path = CONFIG_PATH) -> None:
        self._path = config_path
        self._settings = AnvilSettings()
        self._ensure_directory()
        self._load()

    def _ensure_directory(self) -> None:
        """Create ~/.anvil/ and subdirectories on first run."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        for subdir in ("sessions", "memory", "logs"):
            (self._path.parent / subdir).mkdir(exist_ok=True)

    def _load(self) -> None:
        """Load settings from disk."""
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text())
            self._settings = AnvilSettings(**raw)
        except (json.JSONDecodeError, Exception) as exc:
            logger.warning("Failed to load config: %s", exc)

    def _save(self) -> None:
        """Persist settings to disk."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            self._settings.model_dump_json(indent=2) + "\n"
        )

    @property
    def settings(self) -> AnvilSettings:
        return self._settings

    def get(self, key: str) -> Any:
        """Get a single setting by key."""
        if hasattr(self._settings, key):
            return getattr(self._settings, key)
        return None

    def get_all(self) -> dict[str, Any]:
        """Return all settings as a dict."""
        return self._settings.model_dump()

    def set(self, key: str, value: Any) -> None:
        """Set a single setting and persist."""
        if not hasattr(self._settings, key):
            raise KeyError(f"Unknown setting: {key}")
        setattr(self._settings, key, value)
        self._save()

    def update(self, values: dict[str, Any]) -> None:
        """Update multiple settings and persist."""
        for key, value in values.items():
            if hasattr(self._settings, key):
                setattr(self._settings, key, value)
        self._save()

    def get_api_key(self) -> str | None:
        """Return the API key from env var, falling back to config."""
        env_key = os.environ.get("ANTHROPIC_API_KEY")
        if env_key:
            return env_key
        return self._settings.api_key or None
