"""Tests for the endpoint manager."""

import json
import tempfile
from pathlib import Path

import pytest

from anvil_agent.services.endpoint_manager import EndpointConfig, EndpointManager


@pytest.fixture
def tmp_config(tmp_path: Path) -> Path:
    return tmp_path / "endpoints.json"


@pytest.fixture
def manager(tmp_config: Path) -> EndpointManager:
    return EndpointManager(config_path=tmp_config)


class TestEndpointManager:
    def test_empty_list(self, manager: EndpointManager):
        assert manager.list() == []

    def test_add_and_get(self, manager: EndpointManager):
        ep = EndpointConfig(
            name="local-llm",
            base_url="http://localhost:8080",
            api_key="sk-test",
            default_model="llama3",
        )
        manager.add(ep)
        assert len(manager.list()) == 1

        got = manager.get("local-llm")
        assert got is not None
        assert got.base_url == "http://localhost:8080"
        assert got.api_key == "sk-test"

    def test_add_duplicate_raises(self, manager: EndpointManager):
        ep = EndpointConfig(name="dup", base_url="http://localhost:8080")
        manager.add(ep)
        with pytest.raises(ValueError, match="already exists"):
            manager.add(ep)

    def test_update(self, manager: EndpointManager):
        ep = EndpointConfig(name="test", base_url="http://old:8080")
        manager.add(ep)
        updated = manager.update("test", base_url="http://new:9090")
        assert updated.base_url == "http://new:9090"

    def test_update_nonexistent_raises(self, manager: EndpointManager):
        with pytest.raises(KeyError, match="not found"):
            manager.update("nope", base_url="x")

    def test_delete(self, manager: EndpointManager):
        ep = EndpointConfig(name="del-me", base_url="http://localhost:8080")
        manager.add(ep)
        assert manager.delete("del-me") is True
        assert manager.get("del-me") is None
        assert manager.list() == []

    def test_delete_nonexistent(self, manager: EndpointManager):
        assert manager.delete("nope") is False

    def test_persistence(self, tmp_config: Path):
        mgr1 = EndpointManager(config_path=tmp_config)
        mgr1.add(EndpointConfig(name="persist", base_url="http://localhost:1234"))

        mgr2 = EndpointManager(config_path=tmp_config)
        assert len(mgr2.list()) == 1
        assert mgr2.get("persist") is not None

    def test_get_nonexistent(self, manager: EndpointManager):
        assert manager.get("nope") is None

    def test_config_file_created(self, tmp_config: Path, manager: EndpointManager):
        manager.add(EndpointConfig(name="x", base_url="http://x"))
        assert tmp_config.exists()
        data = json.loads(tmp_config.read_text())
        assert len(data) == 1
