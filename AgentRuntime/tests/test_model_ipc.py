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


# ── cancel ──────────────────────────────────────────────────────────────────

import hashlib  # noqa: E402

import httpx  # noqa: E402

FILE = f"m-{SMALL.quant}.gguf"
BODY = bytes(range(256)) * 40


class Stalling(httpx.AsyncByteStream):
    """Sends a first chunk, signals, then waits (or fails) before the rest."""

    def __init__(self, started: asyncio.Event, fail: bool = False) -> None:
        self.started, self.fail = started, fail

    async def __aiter__(self):
        yield BODY[:2048]
        self.started.set()
        if self.fail:
            raise httpx.ReadError("connection dropped")
        await asyncio.Event().wait()  # until cancelled


def stalling_hub(started: asyncio.Event, fail: bool = False) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tree/main"):
            return httpx.Response(200, json=[{"type": "file", "path": FILE, "size": len(BODY), "lfs": {"oid": hashlib.sha256(BODY).hexdigest()}}])
        return httpx.Response(200, stream=Stalling(started, fail))

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def wait_for(cond, timeout=5.0):
    async with asyncio.timeout(timeout):
        while not cond():
            await asyncio.sleep(0.01)


async def start_download(tmp_path, fail=False):
    rt, events = make_runtime(tmp_path, 512)
    started = asyncio.Event()
    rt._llama._http = stalling_hub(started, fail)
    assert (await rt._handle_model_download({"model_id": SMALL.id}, None))["status"] == "downloading"
    await asyncio.wait_for(started.wait(), 5)
    part = rt._llama.model_dir(SMALL) / (FILE + ".part")
    await wait_for(lambda: part.exists() or SMALL.id not in rt._downloads)  # aiter_bytes buffers 1 MiB, so it may still be empty
    return rt, events, part


async def test_cancel_removes_model_dir_and_part_files(tmp_path):
    rt, events, part = await start_download(tmp_path)
    assert part.exists()
    result = await rt._handle_model_cancel_download({"model_id": SMALL.id}, None)
    assert result == {"status": "cancelled", "model_id": SMALL.id}
    assert not rt._llama.model_dir(SMALL).exists() and rt._downloads == {}
    assert ("model.download_progress", {"model_id": SMALL.id, "status": "cancelled"}) in events


async def test_cancel_when_not_downloading_keeps_a_complete_model(tmp_path):
    rt, _ = make_runtime(tmp_path, 512)
    d = rt._llama.model_dir(SMALL)
    d.mkdir(parents=True)
    (d / "m.gguf").write_bytes(b"ab")
    (d / "manifest.json").write_text(
        '{"repo": "%s", "complete": true, "files": [{"name": "m.gguf", "size": 2}]}' % SMALL.hf_repo
    )
    result = await rt._handle_model_cancel_download({"model_id": SMALL.id}, None)
    assert result["status"] == "not_downloading" and (d / "m.gguf").exists()
    assert (await rt._handle_model_cancel_download({"model_id": "nope"}, None)).get("error")


async def test_failed_download_keeps_part_file_then_cancel_removes_it(tmp_path):
    rt, events, part = await start_download(tmp_path, fail=True)
    await wait_for(lambda: SMALL.id not in rt._downloads)
    assert part.exists()  # kept so Retry can resume
    assert any(p.get("status") == "error" for _, p in events)
    result = await rt._handle_model_cancel_download({"model_id": SMALL.id}, None)
    assert result["status"] == "cancelled" and not rt._llama.model_dir(SMALL).exists()
