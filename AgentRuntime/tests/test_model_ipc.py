"""Handlers behind model.list / model.download / model.cancel_download, called directly on a bare runtime object."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from anvil_agent.main import AnvilRuntime
from anvil_agent.services.llama_cpp_service import LlamaCppService
from anvil_agent.services.model_catalog import MODEL_CATALOG, get_model_by_id

SCOUT = next(m for m in MODEL_CATALOG if "scout" in m.id)
SMALL = min(MODEL_CATALOG, key=lambda m: m.min_ram_gb)


def make_runtime(tmp_path, ram: int | None) -> tuple[AnvilRuntime, list[tuple[str, dict]]]:
    rt = AnvilRuntime.__new__(AnvilRuntime)
    events: list[tuple[str, dict]] = []

    async def broadcast(method, params):
        events.append((method, params))

    rt._router = SimpleNamespace(list_models=lambda: [], active_model_id=None)
    rt._settings = SimpleNamespace(get=lambda key: None)
    rt._llama = LlamaCppService(models_dir=tmp_path)
    rt._downloads = {}
    rt._progress = {}
    rt._total_ram_gb = ram
    rt._broadcast = broadcast
    rt._broadcast_sync = lambda method, params: events.append((method, params))
    return rt, events


def local(models):
    return [m for m in models if m["provider"] == "local"]


async def test_list_hides_models_that_do_not_fit(tmp_path):
    rt, _ = make_runtime(tmp_path, 8)
    listed = local(await rt._handle_model_list({}, None))
    assert listed and all(m["min_ram_gb"] <= 8 for m in listed)
    assert SCOUT.id not in {m["id"] for m in listed}


async def test_list_keeps_downloaded_unfit_model(tmp_path, monkeypatch):
    rt, _ = make_runtime(tmp_path, 8)
    monkeypatch.setattr(rt._llama, "is_downloaded", lambda entry: entry.id == SCOUT.id)
    listed = {m["id"]: m for m in local(await rt._handle_model_list({}, None))}
    assert listed[SCOUT.id]["status"] == "available"


async def test_list_shows_progress_for_downloading(tmp_path):
    rt, _ = make_runtime(tmp_path, 512)
    rt._downloads[SMALL.id] = asyncio.ensure_future(asyncio.sleep(10))
    rt._progress[SMALL.id] = {"done": 5, "total": 10}
    try:
        row = next(m for m in local(await rt._handle_model_list({}, None)) if m["id"] == SMALL.id)
        assert row["status"] == "downloading" and row["progress"] == {"done": 5, "total": 10}
        assert row["download_gb"] == SMALL.download_gb
    finally:
        rt._downloads[SMALL.id].cancel()


async def test_list_hides_nothing_when_ram_unknown(tmp_path):
    rt, _ = make_runtime(tmp_path, None)
    assert len(local(await rt._handle_model_list({}, None))) == len(MODEL_CATALOG)


async def test_download_rejects_unfit_model(tmp_path):
    rt, _ = make_runtime(tmp_path, 8)
    result = await rt._handle_model_download({"model_id": SCOUT.id}, None)
    assert "RAM" in result["error"]


async def test_download_rejects_second_concurrent_download(tmp_path):
    rt, _ = make_runtime(tmp_path, 512)
    other = next(m for m in MODEL_CATALOG if m.id != SMALL.id)
    rt._downloads[other.id] = asyncio.ensure_future(asyncio.sleep(10))
    try:
        result = await rt._handle_model_download({"model_id": SMALL.id}, None)
        assert "another download" in result["error"].lower()
    finally:
        rt._downloads[other.id].cancel()
