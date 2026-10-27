"""The catalog checker's judgement, against synthetic repository listings (no network)."""

from __future__ import annotations

from anvil_agent.services.catalog_check import GIB, assess
from anvil_agent.services.model_catalog import ModelCatalogEntry


def entry(**kw) -> ModelCatalogEntry:
    base = dict(
        id="t", name="T", provider="p", parameters="8B", min_ram_gb=8, description="d", best_for="b",
        supports_tools=True, context_window=8192, hf_repo="o/r", quant="Q4_K_M",
    )
    return ModelCatalogEntry(**{**base, **kw})


def f(path: str, gb: float) -> dict:
    return {"type": "file", "path": path, "size": int(gb * GIB)}


def test_a_plausible_entry_is_ok():
    r = assess(entry(min_ram_gb=8), [f("m-Q4_K_M.gguf", 4.7), f("README.md", 0.001)])
    assert r.level == "ok" and r.quant_used == "Q4_K_M" and r.download_gb == 4.7


def test_min_ram_below_the_download_size_is_flagged_with_a_suggestion():
    r = assess(entry(min_ram_gb=12), [f("m-Q4_K_M.gguf", 60.0)])
    assert r.level == "warning" and r.suggested_min_ram_gb == 66
    assert "too low" in r.warnings[0] and "suggest 66" in r.warnings[0]


def test_a_missing_quant_falls_back_with_a_warning():
    r = assess(entry(min_ram_gb=16), [f("m-Q5_K_M.gguf", 5.5)])
    assert r.level == "warning" and r.quant_used == "Q5_K_M" and "Q4_K_M" in r.warnings[0]


def test_a_repo_without_gguf_files_is_an_error():
    r = assess(entry(), [f("model.safetensors", 4.0), f("mmproj-F16.gguf", 1.0)])
    assert r.level == "error" and "no usable .gguf" in r.errors[0]


def test_an_incomplete_split_model_is_an_error():
    r = assess(entry(), [f("m-Q4_K_M-00001-of-00003.gguf", 10), f("m-Q4_K_M-00002-of-00003.gguf", 10)])
    assert r.level == "error" and "2 of 3" in r.errors[0]


def test_split_models_are_sized_by_all_shards():
    shards = [f(f"m-Q4_K_M-0000{i}-of-00003.gguf", 7.0) for i in (1, 2, 3)]
    r = assess(entry(min_ram_gb=24), shards)
    assert r.download_gb == 21.0 and r.level == "ok"
