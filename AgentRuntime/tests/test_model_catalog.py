"""Tests for the model catalog."""

from anvil_agent.services.model_catalog import (
    MODEL_CATALOG,
    get_cloud_models,
    get_model_by_id,
    get_recommended_models,
)


class TestModelCatalog:
    def test_catalog_not_empty(self):
        assert len(MODEL_CATALOG) > 0

    def test_all_entries_have_required_fields(self):
        for entry in MODEL_CATALOG:
            assert entry.id
            assert entry.name
            assert entry.provider
            assert entry.parameters
            assert entry.min_ram_gb > 0
            assert entry.ollama_tag
            assert entry.context_window > 0

    def test_unique_ids(self):
        ids = [m.id for m in MODEL_CATALOG]
        assert len(ids) == len(set(ids)), "Duplicate model IDs found"

    def test_get_model_by_id_found(self):
        model = get_model_by_id("gemma3:4b")
        assert model is not None
        assert model.name == "Gemma 3 4B"
        assert model.provider == "google"

    def test_get_model_by_id_not_found(self):
        assert get_model_by_id("nonexistent-model") is None

    def test_recommended_models_4gb(self):
        models = get_recommended_models(4)
        assert len(models) >= 1
        assert all(m.min_ram_gb <= 4 for m in models)

    def test_recommended_models_16gb(self):
        models = get_recommended_models(16)
        assert len(models) >= 4
        assert all(m.min_ram_gb <= 16 for m in models)

    def test_recommended_models_sorted_by_size(self):
        models = get_recommended_models(32)
        ram_values = [m.min_ram_gb for m in models]
        assert ram_values == sorted(ram_values)

    def test_recommended_models_0gb(self):
        models = get_recommended_models(0)
        assert models == []

    def test_cloud_models(self):
        clouds = get_cloud_models()
        assert len(clouds) == 3
        ids = [c["id"] for c in clouds]
        assert "claude-opus-4-6" in ids
        assert "claude-sonnet-4-6" in ids
        assert all(c["supports_tools"] for c in clouds)
