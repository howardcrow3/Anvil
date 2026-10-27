"""llama.cpp integration: GGUF file selection, downloads, binary discovery, server lifecycle, provider."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import stat
import sys
import textwrap
from pathlib import Path

import httpx
import pytest

from anvil_agent.models.llama_cpp_provider import LlamaCppProvider
from anvil_agent.models.types import ChatMessage
from anvil_agent.services.llama_cpp_service import LlamaCppError, LlamaCppService, select_gguf_files
from anvil_agent.services.model_catalog import MODEL_CATALOG, ModelCatalogEntry, get_model_by_id, lookup_context_window

posix_only = pytest.mark.skipif(os.name != "posix", reason="uses a #! script as a fake llama-server")


def f(path: str, size: int = 10, oid: str | None = None) -> dict:
    return {"type": "file", "path": path, "size": size, **({"lfs": {"oid": oid}} if oid else {})}


# ── Choosing files ──────────────────────────────────────────────────────────


def test_select_prefers_the_requested_quant_and_skips_projectors():
    tree = [f("README.md"), f("m-Q8_0.gguf"), f("m-Q4_K_M.gguf"), f("mmproj-m-Q4_K_M.gguf"), {"type": "directory", "path": "x.gguf"}]
    quant, files = select_gguf_files(tree, "Q4_K_M")
    assert quant == "Q4_K_M" and [x["path"] for x in files] == ["m-Q4_K_M.gguf"]


def test_select_does_not_confuse_q4_k_m_with_q4_k_s_or_substrings():
    quant, files = select_gguf_files([f("m-Q4_K_S.gguf"), f("m-Q4_K_M.gguf")], "Q4_K_S")
    assert files[0]["path"] == "m-Q4_K_S.gguf"
    with pytest.raises(LlamaCppError):  # "Q14_K_M" must not satisfy a request for "Q4_K_M"
        select_gguf_files([f("m-Q14_K_M.gguf")], "Q4_K_M")


def test_select_falls_back_to_the_next_available_quant():
    quant, files = select_gguf_files([f("m-Q8_0.gguf"), f("m-F16.gguf")], "Q4_K_M")
    assert quant == "Q8_0" and files[0]["path"] == "m-Q8_0.gguf"


def test_select_prefers_plain_over_vendor_variants():
    _, files = select_gguf_files([f("m-UD-Q4_K_M.gguf"), f("m-Q4_K_M.gguf")], "Q4_K_M")
    assert files[0]["path"] == "m-Q4_K_M.gguf"


def test_select_collects_every_shard_in_order_and_finds_quant_in_subfolders():
    tree = [f(f"Q4_K_M/m-Q4_K_M-0000{i}-of-00003.gguf") for i in (3, 1, 2)] + [f("Q8_0/m-Q8_0.gguf")]
    _, files = select_gguf_files(tree, "Q4_K_M")
    assert [x["path"][-20:] for x in files] == ["-00001-of-00003.gguf", "-00002-of-00003.gguf", "-00003-of-00003.gguf"]


def test_select_rejects_incomplete_shards_and_empty_repos():
    with pytest.raises(LlamaCppError, match="incomplete"):
        select_gguf_files([f("m-Q4_K_M-00001-of-00003.gguf"), f("m-Q4_K_M-00002-of-00003.gguf")], "Q4_K_M")
    with pytest.raises(LlamaCppError, match="no usable"):
        select_gguf_files([f("README.md"), f("mmproj-x.gguf")], "Q4_K_M")


# ── Catalog ─────────────────────────────────────────────────────────────────


def test_every_catalog_entry_names_a_hugging_face_repo():
    for e in MODEL_CATALOG:
        owner, _, name = e.hf_repo.partition("/")
        assert owner and name and "GGUF" in name.upper(), e.id


def test_loaded_context_is_capped_but_known_to_the_agent_loop():
    big = get_model_by_id("gemma4:e4b")
    assert big.context_window > 32768 and big.loaded_context == 32768
    assert lookup_context_window("gemma4:e4b") == 32768  # compaction must use what the server really has


# ── Binary discovery ────────────────────────────────────────────────────────


def _exe(path: Path) -> Path:
    path.write_text("#!/bin/sh\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


@posix_only
def test_binary_resolution_order(tmp_path, monkeypatch):
    monkeypatch.delenv("ANVIL_LLAMA_SERVER", raising=False)
    monkeypatch.delenv("ANVIL_LLAMA_DIR", raising=False)
    explicit, from_env, from_dir = _exe(tmp_path / "a"), _exe(tmp_path / "b"), tmp_path / "dir"
    from_dir.mkdir()
    _exe(from_dir / "llama-server")
    monkeypatch.setenv("ANVIL_LLAMA_DIR", str(from_dir))
    assert LlamaCppService(binary=str(explicit)).resolve_binary() == str(explicit)
    assert LlamaCppService().resolve_binary() == str(from_dir / "llama-server")
    monkeypatch.setenv("ANVIL_LLAMA_SERVER", str(from_env))
    assert LlamaCppService().resolve_binary() == str(from_env)


# ── Downloading ─────────────────────────────────────────────────────────────

ENTRY = ModelCatalogEntry(
    id="test:tiny", name="Tiny", provider="test", parameters="1M", min_ram_gb=1, description="", best_for="",
    supports_tools=False, context_window=2048, hf_repo="acme/tiny-GGUF", quant="Q4_K_M",
)
BODY = bytes(range(256)) * 40  # 10 KiB, not repeatable by accident


def hub(tree_extra=None, body=BODY, oid=None, seen=None):
    oid = oid or hashlib.sha256(body).hexdigest()

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append((request.url.path, request.headers.get("range")))
        if request.url.path == "/api/models/acme/tiny-GGUF/tree/main":
            return httpx.Response(200, json=[f("tiny-Q4_K_M.gguf", len(body), oid), f("README.md"), *(tree_extra or [])])
        if request.url.path == "/acme/tiny-GGUF/resolve/main/tiny-Q4_K_M.gguf":
            rng = request.headers.get("range")
            if rng:
                start = int(rng.split("=")[1].split("-")[0])
                return httpx.Response(206, content=body[start:])
            return httpx.Response(200, content=body)
        return httpx.Response(404)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_download_verifies_and_records_a_manifest(tmp_path):
    svc = LlamaCppService(models_dir=tmp_path)
    svc._http = hub()
    ticks: list[tuple[int, int]] = []
    assert not svc.is_downloaded(ENTRY)
    path = await svc.download(ENTRY, lambda name, done, total: ticks.append((done, total)))
    assert path.read_bytes() == BODY and svc.model_path(ENTRY) == path
    assert ticks[-1] == (len(BODY), len(BODY))
    assert not list(path.parent.glob("*.part"))
    # A second call is a no-op: nothing is fetched again.
    seen: list = []
    svc._http = hub(seen=seen)
    await svc.download(ENTRY)
    assert seen == []


async def test_download_resumes_a_partial_file_with_a_range_request(tmp_path):
    svc = LlamaCppService(models_dir=tmp_path)
    d = svc.model_dir(ENTRY)
    d.mkdir(parents=True)
    (d / "tiny-Q4_K_M.gguf.part").write_bytes(BODY[:3000])
    seen: list = []
    svc._http = hub(seen=seen)
    path = await svc.download(ENTRY)
    assert path.read_bytes() == BODY
    assert ("/acme/tiny-GGUF/resolve/main/tiny-Q4_K_M.gguf", "bytes=3000-") in seen


async def test_download_rejects_a_corrupt_file_and_leaves_nothing_usable(tmp_path):
    svc = LlamaCppService(models_dir=tmp_path)
    svc._http = hub(oid="0" * 64)
    with pytest.raises(LlamaCppError, match="checksum"):
        await svc.download(ENTRY)
    assert svc.model_path(ENTRY) is None
    assert not list(svc.model_dir(ENTRY).glob("*.part"))


async def test_download_reports_missing_and_gated_repos(tmp_path):
    svc = LlamaCppService(models_dir=tmp_path)
    svc._http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    with pytest.raises(LlamaCppError, match="not found"):
        await svc.download(ENTRY)
    svc._http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(401)))
    with pytest.raises(LlamaCppError, match="HF_TOKEN"):
        await svc.download(ENTRY)


async def test_a_truncated_download_is_not_reported_as_downloaded(tmp_path):
    svc = LlamaCppService(models_dir=tmp_path)
    await _fake_download(svc)
    path = svc.model_path(ENTRY)
    assert path is not None
    path.write_bytes(b"short")
    assert svc.model_path(ENTRY) is None  # size no longer matches the manifest
    assert svc.delete(ENTRY) and not svc.model_dir(ENTRY).exists()
    assert svc.delete(ENTRY) is False


async def _fake_download(svc: LlamaCppService) -> Path:
    svc._http = hub()
    path = await svc.download(ENTRY)
    svc._http = httpx.AsyncClient(timeout=httpx.Timeout(10.0))  # the hub stand-in only knows Hugging Face URLs
    return path


# ── Server lifecycle (against a stand-in llama-server) ──────────────────────

FAKE_SERVER = textwrap.dedent(
    """\
    #!{python}
    import argparse, json, sys
    from aiohttp import web

    ap = argparse.ArgumentParser()
    ap.add_argument("-m"); ap.add_argument("--host"); ap.add_argument("--port", type=int)
    ap.add_argument("--api-key"); ap.add_argument("-c"); ap.add_argument("-ngl"); ap.add_argument("--jinja", action="store_true")
    ap.add_argument("--version", action="store_true")
    a = ap.parse_args()
    if a.version:
        print("version: 9999 (fake)"); sys.exit(0)
    if {fail}:
        print("error: unable to load model", file=sys.stderr, flush=True); sys.exit(3)

    async def health(request):
        return web.json_response({{"status": "ok"}})

    async def chat(request):
        if request.headers.get("Authorization") != "Bearer " + a.api_key:
            return web.json_response({{"error": "bad key"}}, status=401)
        body = await request.json()
        resp = web.StreamResponse(headers={{"Content-Type": "text/event-stream"}})
        await resp.prepare(request)
        for piece in ("hello from ", "the fake server"):
            chunk = {{"id": "1", "object": "chat.completion.chunk", "model": body["model"],
                     "choices": [{{"index": 0, "delta": {{"content": piece}}, "finish_reason": None}}]}}
            await resp.write(("data: " + json.dumps(chunk) + "\\n\\n").encode())
        done = {{"id": "1", "object": "chat.completion.chunk", "model": body["model"],
                "choices": [{{"index": 0, "delta": {{}}, "finish_reason": "stop"}}]}}
        await resp.write(("data: " + json.dumps(done) + "\\n\\ndata: [DONE]\\n\\n").encode())
        return resp

    app = web.Application()
    app.router.add_get("/health", health)
    app.router.add_post("/v1/chat/completions", chat)
    web.run_app(app, host=a.host, port=a.port, print=None)
    """
)


def fake_binary(tmp_path: Path, fail: bool = False) -> str:
    p = tmp_path / ("llama-fail" if fail else "llama-server")
    p.write_text(FAKE_SERVER.format(python=sys.executable, fail=fail))
    p.chmod(0o755)
    return str(p)


async def service_with_model(tmp_path: Path, **kw) -> LlamaCppService:
    svc = LlamaCppService(models_dir=tmp_path / "models", state_dir=tmp_path / "run", **kw)
    await _fake_download(svc)
    return svc


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


@posix_only
async def test_server_starts_serves_with_its_key_and_is_stopped(tmp_path):
    svc = await service_with_model(tmp_path, binary=fake_binary(tmp_path))
    try:
        base_url, key = await svc.ensure_running(ENTRY)
        pid = svc._proc.pid
        # Same endpoint is reused, not restarted.
        assert await svc.ensure_running(ENTRY) == (base_url, key)
        assert svc._proc.pid == pid
        async with httpx.AsyncClient() as c:
            ok = await c.post(f"{base_url}/v1/chat/completions", json={"model": "x", "messages": []}, headers={"Authorization": f"Bearer {key}"})
            denied = await c.post(f"{base_url}/v1/chat/completions", json={"model": "x", "messages": []})
        assert ok.status_code == 200 and denied.status_code == 401
        state = svc._state_path(ENTRY)
        assert state.exists() and stat.S_IMODE(state.stat().st_mode) == 0o600
    finally:
        await svc.close()
    await asyncio.sleep(0.2)
    assert not pid_alive(pid)
    assert not state.exists()


@posix_only
async def test_provider_streams_from_the_server_through_the_openai_client(tmp_path):
    svc = await service_with_model(tmp_path, binary=fake_binary(tmp_path))
    try:
        provider = LlamaCppProvider(ENTRY, svc)
        assert await provider.health_check()
        text = "".join([c.delta_text async for c in provider.chat([ChatMessage(role="user", content="hi")])])
        assert text == "hello from the fake server"
    finally:
        await svc.close()


@posix_only
async def test_a_second_service_adopts_the_running_server_instead_of_starting_another(tmp_path):
    first = await service_with_model(tmp_path, binary=fake_binary(tmp_path))
    try:
        endpoint = await first.ensure_running(ENTRY)
        second = LlamaCppService(models_dir=tmp_path / "models", state_dir=tmp_path / "run", binary=str(tmp_path / "does-not-exist"))
        assert await second.ensure_running(ENTRY) == endpoint  # no binary needed: nothing is spawned
        assert second._proc is None
        await second.stop()  # must not kill a server it does not own
        assert pid_alive(first._proc.pid)
        await second.close()
    finally:
        await first.close()


@posix_only
async def test_a_server_that_dies_is_restarted_on_the_next_request(tmp_path):
    svc = await service_with_model(tmp_path, binary=fake_binary(tmp_path))
    try:
        first = await svc.ensure_running(ENTRY)
        os.killpg(svc._proc.pid, 9)
        await svc._proc.wait()
        second = await svc.ensure_running(ENTRY)
        assert second != first and svc._proc.returncode is None
    finally:
        await svc.close()


@posix_only
async def test_startup_failure_surfaces_the_servers_own_message(tmp_path):
    svc = await service_with_model(tmp_path, binary=fake_binary(tmp_path, fail=True))
    try:
        with pytest.raises(LlamaCppError, match="unable to load model"):
            await svc.ensure_running(ENTRY)
    finally:
        await svc.close()


async def test_errors_tell_the_user_what_to_do(tmp_path, monkeypatch):
    svc = LlamaCppService(models_dir=tmp_path / "models", state_dir=tmp_path / "run")
    monkeypatch.setattr(svc, "resolve_binary", lambda: None)  # whatever is installed on this machine
    with pytest.raises(LlamaCppError, match="not downloaded"):
        await svc.ensure_running(ENTRY)
    await _fake_download(svc)
    with pytest.raises(LlamaCppError, match="llama-server was not found"):
        await svc.ensure_running(ENTRY)
    await svc.close()


@posix_only
async def test_version_reads_the_binarys_own_report(tmp_path):
    svc = LlamaCppService(binary=fake_binary(tmp_path))
    assert await svc.version() == "9999 (fake)"
    await svc.close()


# ── Against the real llama.cpp (CI sets these; skipped otherwise) ───────────


@pytest.mark.skipif(not (os.environ.get("ANVIL_LLAMA_SERVER") and os.environ.get("ANVIL_TEST_GGUF")), reason="needs ANVIL_LLAMA_SERVER and ANVIL_TEST_GGUF")
async def test_real_llama_server_loads_a_model_and_answers(tmp_path):
    gguf = Path(os.environ["ANVIL_TEST_GGUF"])
    svc = LlamaCppService(models_dir=tmp_path / "models", state_dir=tmp_path / "run")
    d = svc.model_dir(ENTRY)
    d.mkdir(parents=True)
    (d / gguf.name).write_bytes(gguf.read_bytes())
    (d / "manifest.json").write_text(
        json.dumps({"repo": ENTRY.hf_repo, "complete": True, "files": [{"name": gguf.name, "size": gguf.stat().st_size}]})
    )
    try:
        assert await svc.version()
        base_url, key = await svc.ensure_running(ENTRY)
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(f"{base_url}/completion", json={"prompt": "Once upon a time", "n_predict": 4}, headers={"Authorization": f"Bearer {key}"})
        assert r.status_code == 200 and r.json()["content"]
        async with httpx.AsyncClient() as c:
            assert (await c.post(f"{base_url}/completion", json={"prompt": "x", "n_predict": 1})).status_code == 401
    finally:
        await svc.close()


# ── Runtime wiring ──────────────────────────────────────────────────────────


def _runtime_stub(tmp_path: Path):
    from types import SimpleNamespace

    from anvil_agent.models.router import ModelRouter

    return SimpleNamespace(
        _llama=LlamaCppService(models_dir=tmp_path / "models", state_dir=tmp_path / "run"),
        _downloads={},
        _router=ModelRouter(),
        _settings=SimpleNamespace(get=lambda k, d=None: d, get_api_key=lambda: ""),
    )


def test_selecting_a_catalog_model_builds_a_llama_cpp_provider(tmp_path):
    from anvil_agent.main import AnvilRuntime

    rt = _runtime_stub(tmp_path)
    kind, provider = AnvilRuntime._create_provider_for_model(rt, "gemma4:e4b")
    assert kind == "local" and isinstance(provider, LlamaCppProvider) and provider.model_name == "gemma4:e4b"
    assert AnvilRuntime._create_provider_for_model(rt, "no-such-model") is None


async def test_model_list_reports_whether_each_local_model_is_on_disk(tmp_path):
    from anvil_agent.main import AnvilRuntime

    rt = _runtime_stub(tmp_path)
    entry = get_model_by_id("gemma4:e2b")
    d = rt._llama.model_dir(entry)
    d.mkdir(parents=True)
    (d / "m.gguf").write_bytes(b"ab")
    (d / "manifest.json").write_text(json.dumps({"repo": entry.hf_repo, "complete": True, "files": [{"name": "m.gguf", "size": 2}]}))
    rt._downloads["gemma4:e4b"] = object()
    status = {m["id"]: m["status"] for m in await AnvilRuntime._handle_model_list(rt, {}, None) if m["provider"] == "local"}
    assert status["gemma4:e2b"] == "available"
    assert status["gemma4:e4b"] == "downloading"
    assert status["qwen3:8b"] == "downloadable"


async def test_model_download_and_delete_guard_rails(tmp_path):
    from anvil_agent.main import AnvilRuntime

    rt = _runtime_stub(tmp_path)
    assert "error" in await AnvilRuntime._handle_model_download(rt, {"model_id": "nope"}, None)
    assert "error" in await AnvilRuntime._handle_model_delete(rt, {"model_id": "nope"}, None)
    rt._downloads["gemma4:e2b"] = object()
    assert "in progress" in (await AnvilRuntime._handle_model_delete(rt, {"model_id": "gemma4:e2b"}, None))["error"]
    rt._downloads.clear()
    rt._router.register("gemma4:e2b", LlamaCppProvider(get_model_by_id("gemma4:e2b"), rt._llama), provider_type="local")
    assert "active" in (await AnvilRuntime._handle_model_delete(rt, {"model_id": "gemma4:e2b"}, None))["error"]
    await rt._llama.close()
