"""Tests for the settings manager."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from anvil_agent.settings import AnvilSettings, SettingsManager


@pytest.fixture
def tmp_config(tmp_path: Path) -> Path:
    return tmp_path / "config.json"


@pytest.fixture
def manager(tmp_config: Path) -> SettingsManager:
    return SettingsManager(config_path=tmp_config)


class TestAnvilSettings:
    def test_defaults(self):
        s = AnvilSettings()
        assert s.api_key == ""
        assert s.default_model == "claude-sonnet-4-20250514"
        assert s.default_provider == "claude"
        assert s.permission_mode == "ask"
        assert s.ollama_port == 11434
        assert s.endpoints == []
        assert s.mcp_servers == []
        assert s.tool_allow_list == []
        assert s.tool_deny_list == []

    def test_custom_values(self):
        s = AnvilSettings(api_key="sk-test", ollama_port=9999)
        assert s.api_key == "sk-test"
        assert s.ollama_port == 9999


class TestSettingsManager:
    def test_get_default(self, manager: SettingsManager):
        assert manager.get("default_model") == "claude-sonnet-4-20250514"

    def test_get_nonexistent(self, manager: SettingsManager):
        assert manager.get("nonexistent_key") is None

    def test_set_and_get(self, manager: SettingsManager):
        manager.set("api_key", "sk-new")
        assert manager.get("api_key") == "sk-new"

    def test_set_unknown_key_raises(self, manager: SettingsManager):
        with pytest.raises(KeyError, match="Unknown setting"):
            manager.set("totally_fake", "value")

    def test_update_multiple(self, manager: SettingsManager):
        manager.update({"api_key": "sk-multi", "ollama_port": 5555})
        assert manager.get("api_key") == "sk-multi"
        assert manager.get("ollama_port") == 5555

    def test_get_all(self, manager: SettingsManager):
        result = manager.get_all()
        assert isinstance(result, dict)
        assert "api_key" in result
        assert "default_model" in result

    def test_persistence(self, tmp_config: Path):
        mgr1 = SettingsManager(config_path=tmp_config)
        mgr1.set("api_key", "sk-persist")

        mgr2 = SettingsManager(config_path=tmp_config)
        assert mgr2.get("api_key") == "sk-persist"

    def test_config_file_written(self, tmp_config: Path, manager: SettingsManager):
        manager.set("api_key", "test")
        assert tmp_config.exists()
        data = json.loads(tmp_config.read_text())
        assert data["api_key"] == "test"

    def test_creates_subdirectories(self, tmp_config: Path):
        mgr = SettingsManager(config_path=tmp_config)
        parent = tmp_config.parent
        assert (parent / "sessions").is_dir()
        assert (parent / "memory").is_dir()
        assert (parent / "logs").is_dir()

    def test_get_api_key_from_env(self, tmp_config: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-env-key")
        mgr = SettingsManager(config_path=tmp_config)
        assert mgr.get_api_key() == "sk-env-key"

    def test_get_api_key_from_config(self, tmp_config: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        mgr = SettingsManager(config_path=tmp_config)
        mgr.set("api_key", "sk-config-key")
        assert mgr.get_api_key() == "sk-config-key"

    def test_get_api_key_none_when_empty(self, tmp_config: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        mgr = SettingsManager(config_path=tmp_config)
        assert mgr.get_api_key() is None

    def test_settings_property(self, manager: SettingsManager):
        assert isinstance(manager.settings, AnvilSettings)
