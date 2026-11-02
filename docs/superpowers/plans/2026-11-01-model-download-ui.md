# Model Download / Delete UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users download, cancel and delete local llama.cpp models from Settings, offering only models that fit this machine, with Cancel removing all partial data.

**Architecture:** The Python runtime gains cross-platform RAM detection, a fit filter and disk check, a `model.cancel_download` RPC and progress in `model.list`. The Electron renderer gets a pure download-state reducer (same pattern as `chatState.ts`), store actions, and a Models tab in Settings.

**Tech Stack:** Python 3 / pydantic v2 / asyncio / pytest (`AgentRuntime/`); React + zustand + vitest + Playwright (`Desktop/`).

**Spec:** `docs/superpowers/specs/2026-11-01-model-download-design.md`

## Global Constraints

- Python: Pydantic v2, asyncio, type hints everywhere (CLAUDE.md).
- No new Python dependencies (RAM detection uses the stdlib; the runtime is bundled per platform).
- Fit rule: `entry.min_ram_gb <= total_ram_gb`, total RAM rounded to nearest GB (`round(bytes / 2**30)`).
- Disk rule: free space in the models dir >= bytes still to fetch + 1 GiB.
- Cancel deletes the whole model dir; a failed download keeps partial files.
- Python checks: `cd AgentRuntime && python -m pytest --ignore=tests/test_build_install.py`. Desktop checks: `cd Desktop && npm run typecheck && npm test`.

## Review Focus

- Cancel arrives just as the download finishes: end state is either a complete model or nothing, never a half-state.
- RAM cannot be detected (unsupported OS, parse failure): nothing is hidden.
- A model already downloaded but too big for this machine (disk moved between machines): still listed so it can be deleted.
- Download fails midway (network, disk full), then Retry: resumes from the kept `.part`; a later Cancel removes it.
- Window opened or runtime reconnected mid-download: bar appears from `model.list`, not a stale Download button.

---

### Task 1: Cross-platform RAM detection

`services/system_info.py` only works on macOS (`sysctl`, `vm_stat`) and falls back to 8 GB elsewhere, which would hide every big model on Windows/Linux.

**Files:**
- Modify: `AgentRuntime/anvil_agent/services/system_info.py`
- Test: `AgentRuntime/tests/test_system_info.py`

**Interfaces:**
- Produces: `detect_total_ram_gb() -> int | None` (rounded GB, `None` if unknown). `_get_total_ram_gb()` keeps its signature and returns `detect_total_ram_gb() or 8`.

- [ ] **Step 1: Write failing tests** in `test_system_info.py`: `test_linux_meminfo_parsed` (monkeypatch `platform.system` to `"Linux"` and the file reader to return `"MemTotal:       32768000 kB\n"`; expect 31 -> assert `detect_total_ram_gb() == round(32768000*1024/2**30)`), `test_windows_uses_global_memory_status` (monkeypatch `platform.system` to `"Windows"` and the ctypes reader helper `_windows_total_bytes` to return `64 * 2**30 - 100_000_000`; expect 64), `test_unknown_returns_none` (reader raises `OSError`; expect `None`), `test_legacy_fallback_is_8` (`_get_total_ram_gb()` returns 8 when detection returns `None`).
- [ ] **Step 2: Run** `cd AgentRuntime && python -m pytest tests/test_system_info.py -q`. Expected: the four new tests FAIL (names undefined).
- [ ] **Step 3: Implement** `detect_total_ram_gb`, with helpers `_linux_total_bytes() -> int` (read `/proc/meminfo` `MemTotal` kB), `_windows_total_bytes() -> int` (ctypes `GlobalMemoryStatusEx`, `ullTotalPhys`), and the existing macOS `sysctl hw.memsize` path. Dispatch on `platform.system()`; any exception returns `None`. Make `_get_total_ram_gb` use it.
- [ ] **Step 4: Run** the same command. Expected: all PASS.
- [ ] **Step 5: Commit** `feat: detect total RAM on Linux and Windows`.

### Task 2: Fit filter, catalog sizes, progress in `model.list`

**Files:**
- Modify: `AgentRuntime/anvil_agent/services/model_catalog.py`, `AgentRuntime/anvil_agent/main.py` (`_handle_model_list` ~L800, `_handle_model_download` ~L843, `__init__` near L166)
- Test: `AgentRuntime/tests/test_model_catalog.py`, `AgentRuntime/tests/test_model_ipc.py` (new; model it on how `test_ipc_screens.py` builds the runtime)

**Interfaces:**
- Produces: `ModelCatalogEntry.download_gb: float` (copy each entry's value from `size_gb` in `Resources/default-models.json`); `fits_machine(entry: ModelCatalogEntry, total_ram_gb: int | None) -> bool` in `model_catalog.py` (`None` -> `True`). The runtime holds `self._total_ram_gb: int | None` (set from `detect_total_ram_gb()` in `__init__`; tests overwrite it) and `self._progress: dict[str, dict[str, int]]` (`{done, total}`, updated in the progress callback, removed in `finally`).
- `model.list` local entries add `download_gb`, `min_ram_gb`, and `progress` (only while downloading).

- [ ] **Step 1: Write failing tests.** In `test_model_catalog.py`: `test_fits_machine_boundaries` (min_ram 16: fits at 16 and 32, not at 15, and `None` fits); `test_download_gb_matches_default_models_json` (every entry's `download_gb` equals the JSON `size_gb`). In `test_model_ipc.py`: `test_list_hides_models_that_do_not_fit` (`_total_ram_gb = 8`: ids returned for provider `local` all have `min_ram_gb <= 8`); `test_list_keeps_downloaded_unfit_model` (patch `is_downloaded` true for the Scout entry with 8 GB RAM: Scout is listed with status `available`); `test_list_shows_progress_for_downloading` (put an id in `_downloads` and `_progress`: status `downloading`, `progress == {"done": 5, "total": 10}`); `test_download_rejects_unfit_model` (`{"error": ...}` containing `"RAM"`); `test_download_rejects_second_concurrent_download` (error contains `"another download"`).
- [ ] **Step 2: Run** `python -m pytest tests/test_model_catalog.py tests/test_model_ipc.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the field, `fits_machine`, filtering (skip a local entry when `not fits_machine(...)` and it is neither downloaded nor in `_downloads`), the extra list fields, and the two `model.download` guards, in this order: unknown id, already downloaded (`ready`), does not fit (error mentioning RAM), another download running (error mentioning "another download").
- [ ] **Step 4: Run** the full Python suite. Expected: PASS (the drift test in `test_model_catalog.py` still passes).
- [ ] **Step 5: Commit** `feat: only offer local models that fit this machine`.

### Task 3: Disk-space check

**Files:**
- Modify: `AgentRuntime/anvil_agent/services/llama_cpp_service.py` (`download`, ~L218)
- Test: `AgentRuntime/tests/test_llama_cpp.py`

**Interfaces:**
- Consumes: `shutil.disk_usage` (module-level, patchable as `llama_cpp_service.shutil.disk_usage`).
- Produces: `LlamaCppError("not enough disk space for <name>: need X.X GB, only Y.Y GB free")` raised from `download` after listing the repo and before creating the dir or writing any file.

- [ ] **Step 1: Write failing tests**: `test_download_refuses_when_disk_too_small` (fake HF tree with a 10 MiB file, patched `disk_usage` returning `free = 10 MiB`; expect `LlamaCppError` matching `"not enough disk space"` and that the model dir does not exist); `test_disk_check_counts_existing_part_file` (a 9 MiB `.part` already on disk, free = 1 GiB + 2 MiB: download proceeds). Reuse the MockTransport helper already in this file.
- [ ] **Step 2: Run** `python -m pytest tests/test_llama_cpp.py -q -k disk`. Expected: FAIL.
- [ ] **Step 3: Implement** the check using `max(0, total - existing_part_bytes) + 1 GiB` against `shutil.disk_usage(<nearest existing parent of the models dir>).free`.
- [ ] **Step 4: Run** `python -m pytest tests/test_llama_cpp.py -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: check free disk space before downloading a model`.

### Task 4: Cancel removes everything

**Files:**
- Modify: `AgentRuntime/anvil_agent/main.py` (register `model.cancel_download` next to L573; new `_handle_model_cancel_download`; `run()` in `_handle_model_download` handles `CancelledError`)
- Test: `AgentRuntime/tests/test_model_ipc.py`

**Interfaces:**
- Consumes: `LlamaCppService.delete(entry) -> bool` (already `rmtree`s the model dir), `self._downloads`.
- Produces: RPC `model.cancel_download {model_id}` -> `{"status": "cancelled" | "not_downloading", "model_id": str}`; broadcasts `model.download_progress {model_id, status: "cancelled"}`. The handler cancels the task, awaits it, then calls `delete(entry)` so no file handle is open (matters on Windows). If nothing is downloading and the model is complete (or absent), return `not_downloading` and leave it alone; if it is incomplete (kept after an error), remove it and return `cancelled`. A download that fails with an error still keeps its partial files.

- [ ] **Step 1: Write failing tests** with a fake HF transport whose file response streams slowly (an async generator that awaits an `asyncio.Event` between chunks): `test_cancel_removes_model_dir_and_part_files` (start download, wait until the `.part` exists, call cancel; expect `status == "cancelled"`, the model dir is gone, `_downloads` empty, a `cancelled` broadcast recorded); `test_cancel_when_not_downloading` (`not_downloading`, nothing deleted: a completed model's files remain); `test_failed_download_keeps_part_file` (transport raises mid-stream: broadcast `error`, `.part` still on disk); `test_cancel_after_failure_removes_part_file` (cancel on a model that is not downloading but has an incomplete dir with a kept `.part`: returns `cancelled` and the dir is removed; on a complete model it returns `not_downloading` and deletes nothing).
- [ ] **Step 2: Run** `python -m pytest tests/test_model_ipc.py -q -k cancel`. Expected: FAIL.
- [ ] **Step 3: Implement** the handler and the `CancelledError` branch in `run()` (broadcast `cancelled`, re-raise).
- [ ] **Step 4: Run** the full Python suite. Expected: PASS.
- [ ] **Step 5: Commit** `feat: model.cancel_download removes partial downloads`.

### Task 5: Renderer download state and store actions

**Files:**
- Create: `Desktop/src/renderer/src/store/downloadState.ts`, `Desktop/src/renderer/src/lib/formatDownload.ts`
- Modify: `Desktop/src/renderer/src/lib/types.ts` (`ModelInfo`), `Desktop/src/renderer/src/store/app.ts`
- Test: `Desktop/tests/downloadState.test.ts`, `Desktop/tests/formatDownload.test.ts`

**Interfaces:**
- Produces in `types.ts`: `ModelInfo` gains `download_gb?: number; min_ram_gb?: number; progress?: { done: number; total: number }`; `DownloadProgressEvent = { model_id: string; file?: string; done?: number; total?: number; status?: 'ready' | 'error' | 'cancelled'; error?: string }`.
- `downloadState.ts`: `type DownloadEntry = { done: number; total: number; startedAt: number; error?: string }`, `type Downloads = Record<string, DownloadEntry>`, `applyDownloadEvent(state: Downloads, e: DownloadProgressEvent, now: number): Downloads` (progress sets/updates, keeping `startedAt` from the first event; `ready`/`cancelled` remove the entry; `error` keeps it with `error`), `seedFromModels(models: ModelInfo[], now: number): Downloads` (entries for `status === 'downloading'`).
- `formatDownload.ts`: `formatGb(bytes: number): string` (one decimal, `"1.5 GB"`), `describeProgress(e: DownloadEntry, now: number): { percent: number; label: string }` where label is `"1.5 / 4.7 GB · 12 MB/s · 4 min left"` and speed/ETA are omitted until at least 2 s have elapsed.
- Store: `downloads: Downloads`; actions `downloadModel(id)`, `cancelDownload(id)`, `deleteModel(id)` calling `model.download`, `model.cancel_download`, `model.delete`; `rpc.on('model.download_progress', ...)` applies the event and calls `refreshModels()` on `ready`/`cancelled`/`error`; `refreshModels` also reseeds `downloads` for models the store has no entry for. RPC `{error}` results become `setNotice`.

- [ ] **Step 1: Write failing tests**: reducer — `progress events accumulate and keep the first startedAt`, `ready removes the entry`, `cancelled removes the entry`, `error keeps the entry with its message`, `seedFromModels picks up downloading models only`; formatting — `formatGb(1.5 * 2**30) === "1.5 GB"`, `describeProgress` at 1 s has no speed, at 10 s with 100 MiB done of 1 GiB reports `~10 MB/s` and a minutes-left ETA, percent clamps to 0..100 and is 0 when total is 0.
- [ ] **Step 2: Run** `cd Desktop && npx vitest run tests/downloadState.test.ts tests/formatDownload.test.ts`. Expected: FAIL (modules missing).
- [ ] **Step 3: Implement** the modules and wire the store.
- [ ] **Step 4: Run** `npm run typecheck && npm test`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(desktop): model download state and store actions`.

### Task 6: Fake Hugging Face for end-to-end tests

**Files:**
- Create: `Desktop/e2e/fake_hf.py` (modeled on `e2e/fake_openai.py`: serves `/api/models/<repo>/tree/main` with one small GGUF-named file and `/<repo>/resolve/main/<path>` streaming slowly, honoring `Range`)
- Modify: `AgentRuntime/anvil_agent/services/llama_cpp_service.py` (`HF_BASE` stays the default; the service reads `os.environ.get("ANVIL_HF_BASE", HF_BASE)` at construction), `Desktop/e2e/global-setup.ts` (start the fake, export `ANVIL_HF_BASE`), `Desktop/e2e/models.spec.ts`
- Test: `AgentRuntime/tests/test_llama_cpp.py::test_hf_base_env_override`

**Interfaces:**
- Produces: env `ANVIL_HF_BASE` (URL, no trailing slash) honored by the runtime; the e2e picks the catalog entry with the smallest `min_ram_gb` from `model.list` so the RAM filter cannot hide it on CI runners.

- [ ] **Step 1: Write failing test** `test_hf_base_env_override` (set `ANVIL_HF_BASE`, construct the service, `_list_repo` hits the override host through MockTransport) and a Playwright test in `Desktop/e2e/models.spec.ts` (`download completes and the model becomes selectable`) that drives the RPCs through the page's existing RPC client, since the UI does not exist yet.
- [ ] **Step 2: Run** `python -m pytest tests/test_llama_cpp.py -q -k hf_base`. Expected: FAIL.
- [ ] **Step 3: Implement** the override, fake server and global-setup wiring.
- [ ] **Step 4: Run** all Python and Desktop checks including `npm run test:e2e`. Expected: PASS; confirm `electron-e2e` is unaffected.
- [ ] **Step 5: Commit** `test: e2e coverage for model download with a fake Hugging Face`.

### Task 7: Models tab and picker wording

**Files:**
- Create: `Desktop/src/renderer/src/settings/ModelsSettings.tsx`
- Modify: `Desktop/src/renderer/src/settings/SettingsDialog.tsx` (add tab `{ id: 'models', label: 'Models' }` and panel), `Desktop/src/renderer/src/store/app.ts` (`SettingsTab` gains `'models'`), `Desktop/src/renderer/src/components/ModelSelector.tsx` (label `" (download in Settings)"` for `downloadable`)

**Interfaces:**
- Consumes: Task 5 store actions and `describeProgress`, `formatGb`.
- Renders local models only. Per row: name, `download_gb` and "needs N GB RAM", then by status: `downloadable` -> Download button (disabled with title "Another download is running" when any other entry is in `downloads`); `downloading` -> progress bar (`role="progressbar"`, `aria-valuenow`), label from `describeProgress`, and a Cancel button whose confirm text says the partial download will be deleted; `available` -> Delete button behind the existing `Modal` confirm showing the GB freed, disabled with a title when `active`. Errors from a failed download show inline with a Retry (Download) button. The elapsed-time label re-renders every second via an interval that only runs while something is downloading.

- [ ] **Step 1: Write a failing Playwright test** `Desktop/e2e/models.spec.ts` using the fake Hugging Face from Task 6. Test names (add to the file): `models tab lists only downloadable local models and shows sizes`, `download shows progress and cancel removes it`, `cancel leaves no files in the models dir`, `delete asks for confirmation`.
- [ ] **Step 2: Run** `cd Desktop && npx playwright test e2e/models.spec.ts`. Expected: FAIL.
- [ ] **Step 3: Implement** the component, tab and picker label.
- [ ] **Step 4: Run** `npm run typecheck && npm test && npm run test:e2e`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(desktop): Models tab with download, cancel and delete`.
