"""llama.cpp (``llama-server``) lifecycle, plus GGUF model download/storage.

One ``llama-server`` process serves one model over an OpenAI-compatible API on 127.0.0.1, protected by a
random API key. Servers are started lazily (first chat with a local model) and shared between Anvil
processes (the main runtime and teammate runtimes) through a small state file per model, so a team of
agents does not load the same weights several times.

The binary is not built here: the desktop app bundles the pinned official llama.cpp release (see
``Resources/llama-cpp.lock.json`` and ``Desktop/scripts/bundle-llama.mjs``), which a scheduled workflow
keeps current.
"""

from __future__ import annotations

import asyncio
import collections
import hashlib
import json
import logging
import os
import re
import secrets
import shutil
import signal
import socket
import subprocess
from pathlib import Path
from typing import Any, Callable

import httpx

from anvil_agent.services.model_catalog import ModelCatalogEntry

logger = logging.getLogger(__name__)

ANVIL_DIR = Path.home() / ".anvil"
MODELS_DIR = ANVIL_DIR / "models"
HF_BASE = "https://huggingface.co"
BINARY_NAME = "llama-server.exe" if os.name == "nt" else "llama-server"

# Used when the repo has no file for the requested quantization: the first one present wins.
QUANT_FALLBACKS = ["Q4_K_M", "Q4_K_S", "Q4_0", "Q5_K_M", "Q5_K_S", "Q6_K", "Q8_0", "MXFP4", "F16", "BF16"]

_SHARD = re.compile(r"-(\d{5})-of-(\d{5})\.gguf$", re.IGNORECASE)

ProgressCallback = Callable[[str, int, int], None]  # (file name, bytes done, bytes total across the model)


class LlamaCppError(RuntimeError):
    """A problem a user can act on (missing binary, model not downloaded, server failed to start)."""


# ── Choosing files from a Hugging Face repo listing ─────────────────────────


def _has_quant(path: str, quant: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9]){re.escape(quant)}(?![A-Za-z0-9])", path, re.IGNORECASE) is not None


def select_gguf_files(tree: list[dict[str, Any]], quant: str) -> tuple[str, list[dict[str, Any]]]:
    """Pick the GGUF file(s) of one model out of a repo's file listing.

    Returns ``(quant_used, files)``; ``files`` has several entries only for a split model (every shard is
    needed, the first one is what llama-server is pointed at). Vision projectors (``mmproj``) are never
    the model. If the preferred quantization is missing, the next one from QUANT_FALLBACKS is used.
    """
    ggufs = [
        f for f in tree
        if f.get("type", "file") == "file" and f["path"].lower().endswith(".gguf") and "mmproj" not in f["path"].lower()
    ]
    for q in [quant, *[x for x in QUANT_FALLBACKS if x.lower() != quant.lower()]]:
        matching = [f for f in ggufs if _has_quant(f["path"], q)]
        if not matching:
            continue
        # Prefer a plain build over vendor variants (UD-Q4_K_M, IQ...) of the same quantization.
        matching.sort(key=lambda f: (bool(re.search(r"(^|[/_-])(UD|IQ)", f["path"])), len(f["path"])))
        chosen = matching[0]
        if _SHARD.search(chosen["path"]):
            prefix = _SHARD.sub("", chosen["path"])
            shards = sorted((f for f in matching if _SHARD.sub("", f["path"]) == prefix), key=lambda f: f["path"])
            total = int(_SHARD.search(shards[0]["path"]).group(2))  # type: ignore[union-attr]
            if len(shards) != total:
                raise LlamaCppError(f"incomplete split model in repo: found {len(shards)} of {total} shards for {prefix}")
            return q, shards
        return q, [chosen]
    raise LlamaCppError(f"no usable .gguf file found in the repository (wanted {quant})")


def _local_name(entry: ModelCatalogEntry) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", entry.id)


# ── Service ─────────────────────────────────────────────────────────────────


class LlamaCppService:
    """Finds ``llama-server``, downloads GGUF models, and runs one server per model."""

    START_TIMEOUT = 180  # seconds; loading a large model from a slow disk takes a while
    STOP_TIMEOUT = 8

    def __init__(
        self,
        models_dir: Path | None = None,
        binary: str | None = None,
        state_dir: Path | None = None,
    ) -> None:
        self._models_dir = models_dir or MODELS_DIR
        self._configured_binary = binary or None
        self._state_dir = state_dir or ANVIL_DIR / "run"
        self._lock = asyncio.Lock()
        self._proc: asyncio.subprocess.Process | None = None
        self._owned_model: str | None = None
        self._running: dict[str, tuple[str, str]] = {}  # model id -> (base_url, api key)
        self._stderr: collections.deque[str] = collections.deque(maxlen=60)
        self._tasks: set[asyncio.Task[Any]] = set()
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0), follow_redirects=True)

    # ── Binary ──

    def resolve_binary(self) -> str | None:
        """The llama-server executable: explicit setting, env, the bundled copy, a dev checkout, then PATH."""
        candidates: list[Path] = []
        if self._configured_binary:
            candidates.append(Path(self._configured_binary))
        if os.environ.get("ANVIL_LLAMA_SERVER"):
            candidates.append(Path(os.environ["ANVIL_LLAMA_SERVER"]))
        if os.environ.get("ANVIL_LLAMA_DIR"):
            candidates.append(Path(os.environ["ANVIL_LLAMA_DIR"]) / BINARY_NAME)
        project_root = Path(__file__).resolve().parent.parent.parent.parent
        candidates.append(project_root / "Desktop" / "build" / "runtime" / "llama" / BINARY_NAME)
        for c in candidates:
            if c.is_file() and os.access(str(c), os.X_OK):
                return str(c)
        return shutil.which("llama-server")

    async def version(self) -> str | None:
        """Output of ``llama-server --version`` (the build the app is actually running), or None."""
        binary = self.resolve_binary()
        if binary is None:
            return None
        try:
            proc = await asyncio.create_subprocess_exec(
                binary, "--version", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, env=self._env(binary)
            )
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=20)
        except (OSError, asyncio.TimeoutError):
            return None
        text = out.decode("utf-8", errors="replace")
        m = re.search(r"version:\s*(.+)", text)
        return m.group(1).strip() if m else (text.strip().splitlines() or [None])[-1]

    @staticmethod
    def _env(binary: str) -> dict[str, str]:
        env = os.environ.copy()
        env.pop("ANVIL_WS_TOKEN", None)  # the runtime's auth token is not llama-server's business
        lib_dir = str(Path(binary).resolve().parent)
        for var in ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"):  # shared libraries ship next to the binary
            env[var] = lib_dir + (os.pathsep + env[var] if env.get(var) else "")
        return env

    # ── Models on disk ──

    def model_dir(self, entry: ModelCatalogEntry) -> Path:
        return self._models_dir / _local_name(entry)

    def _manifest(self, entry: ModelCatalogEntry) -> dict[str, Any] | None:
        try:
            data = json.loads((self.model_dir(entry) / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def model_path(self, entry: ModelCatalogEntry) -> Path | None:
        """Path of the (first shard of the) downloaded model, or None if it is not completely downloaded."""
        manifest = self._manifest(entry)
        if not manifest or not manifest.get("complete") or manifest.get("repo") != entry.hf_repo:
            return None
        files = manifest.get("files") or []
        if not files:
            return None
        for f in files:
            p = self.model_dir(entry) / f["name"]
            if not p.is_file() or p.stat().st_size != f["size"]:
                return None
        return self.model_dir(entry) / files[0]["name"]

    def is_downloaded(self, entry: ModelCatalogEntry) -> bool:
        return self.model_path(entry) is not None

    def delete(self, entry: ModelCatalogEntry) -> bool:
        d = self.model_dir(entry)
        if not d.is_dir():
            return False
        shutil.rmtree(d, ignore_errors=True)
        return True

    # ── Download ──

    def _hf_headers(self) -> dict[str, str]:
        token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
        return {"Authorization": f"Bearer {token}"} if token else {}

    async def _list_repo(self, repo: str) -> list[dict[str, Any]]:
        resp = await self._http.get(f"{HF_BASE}/api/models/{repo}/tree/main", params={"recursive": "true"}, headers=self._hf_headers())
        if resp.status_code == 404:
            raise LlamaCppError(f"model repository {repo} was not found on Hugging Face")
        if resp.status_code in (401, 403):
            raise LlamaCppError(f"{repo} needs a Hugging Face login: set HF_TOKEN to a token that can read it")
        resp.raise_for_status()
        return resp.json()

    async def download(self, entry: ModelCatalogEntry, progress: ProgressCallback | None = None) -> Path:
        """Download a catalog model (resuming a partial download); returns the path to load."""
        if (path := self.model_path(entry)) is not None:
            return path
        quant, files = select_gguf_files(await self._list_repo(entry.hf_repo), entry.quant)
        if quant.lower() != entry.quant.lower():
            logger.warning("%s has no %s build; using %s", entry.hf_repo, entry.quant, quant)
        dest_dir = self.model_dir(entry)
        if (dest_dir / "manifest.json").exists():  # a finished download that no longer matches the catalog entry
            shutil.rmtree(dest_dir, ignore_errors=True)
        dest_dir.mkdir(parents=True, exist_ok=True)
        total = sum(int(f.get("size", 0)) for f in files)
        done_before = 0
        records: list[dict[str, Any]] = []
        for f in files:
            name = Path(f["path"]).name
            sha = (f.get("lfs") or {}).get("oid")
            await self._fetch_file(f"{HF_BASE}/{entry.hf_repo}/resolve/main/{f['path']}", dest_dir / name, int(f["size"]), sha,
                                   lambda got, base=done_before, n=name: progress and progress(n, base + got, total))
            done_before += int(f["size"])
            records.append({"name": name, "size": int(f["size"]), "sha256": sha})
        (dest_dir / "manifest.json").write_text(
            json.dumps({"repo": entry.hf_repo, "quant": quant, "complete": True, "files": records}, indent=2), encoding="utf-8"
        )
        return dest_dir / records[0]["name"]

    async def _fetch_file(self, url: str, dest: Path, size: int, sha256: str | None, on_bytes: Callable[[int], None]) -> None:
        part = dest.with_name(dest.name + ".part")
        digest = hashlib.sha256()
        have = part.stat().st_size if part.exists() else 0
        if have > size:
            part.unlink()
            have = 0
        if have:  # resuming: the hash must cover the bytes already on disk
            with part.open("rb") as fh:
                for block in iter(lambda: fh.read(1 << 20), b""):
                    digest.update(block)
        if have < size:
            headers = {**self._hf_headers(), **({"Range": f"bytes={have}-"} if have else {})}
            async with self._http.stream("GET", url, headers=headers, timeout=httpx.Timeout(60.0, connect=15.0)) as resp:
                if resp.status_code == 200 and have:  # server ignored the range: start over
                    have = 0
                    digest = hashlib.sha256()
                    part.unlink(missing_ok=True)
                resp.raise_for_status()
                with part.open("ab") as out:
                    async for block in resp.aiter_bytes(1 << 20):
                        out.write(block)
                        digest.update(block)
                        have += len(block)
                        on_bytes(have)
        if have != size:
            raise LlamaCppError(f"download of {dest.name} ended at {have} of {size} bytes; run it again to resume")
        if sha256 and digest.hexdigest() != sha256:
            part.unlink(missing_ok=True)
            raise LlamaCppError(f"checksum mismatch for {dest.name}; the partial file was removed, run it again")
        os.replace(part, dest)

    # ── Server ──

    def _state_path(self, entry: ModelCatalogEntry) -> Path:
        return self._state_dir / f"llama-server.{_local_name(entry)}.json"

    async def _healthy(self, base_url: str) -> bool:
        try:
            return (await self._http.get(f"{base_url}/health", timeout=3.0)).status_code == 200
        except httpx.HTTPError:
            return False

    async def _adopt_shared(self, entry: ModelCatalogEntry) -> tuple[str, str] | None:
        """Reuse a server another Anvil process already started for this model."""
        try:
            st = json.loads(self._state_path(entry).read_text(encoding="utf-8"))
            base_url, key, pid = str(st["base_url"]), str(st["api_key"]), int(st["pid"])
        except (OSError, ValueError, KeyError, TypeError):
            return None
        if not base_url.startswith("http://127.0.0.1:") or not _pid_alive(pid) or not await self._healthy(base_url):
            return None
        return base_url, key

    async def ensure_running(self, entry: ModelCatalogEntry) -> tuple[str, str]:
        """Return ``(base_url, api_key)`` of a healthy server for the model, starting one if needed."""
        async with self._lock:
            known = self._running.get(entry.id)
            if known and await self._healthy(known[0]):
                return known
            self._running.pop(entry.id, None)

            model = self.model_path(entry)
            if model is None:
                raise LlamaCppError(f"{entry.name} is not downloaded yet. Download it from the model picker first.")
            if (shared := await self._adopt_shared(entry)) is not None:
                self._running[entry.id] = shared
                return shared

            binary = self.resolve_binary()
            if binary is None:
                raise LlamaCppError(
                    "llama-server was not found. Install Anvil from a release build (it bundles llama.cpp), "
                    "put llama-server on PATH, or set ANVIL_LLAMA_SERVER to its location."
                )
            await self._stop_owned()
            port, key = _free_port(), secrets.token_urlsafe(24)
            args = [
                binary, "-m", str(model), "--host", "127.0.0.1", "--port", str(port), "--api-key", key,
                "--jinja", "-c", str(entry.loaded_context), "-ngl", "999",
            ]
            self._stderr.clear()
            try:
                self._proc = await asyncio.create_subprocess_exec(
                    *args, env=self._env(binary), stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
                    start_new_session=(os.name == "posix"),
                )
            except OSError as exc:
                raise LlamaCppError(f"could not start llama-server ({binary}): {exc}") from exc
            self._owned_model = entry.id
            self._spawn(self._pump_stderr(self._proc))

            base_url = f"http://127.0.0.1:{port}"
            loop = asyncio.get_running_loop()
            deadline = loop.time() + self.START_TIMEOUT
            while loop.time() < deadline:
                if self._proc.returncode is not None:
                    raise LlamaCppError(f"llama-server exited with code {self._proc.returncode} while loading {entry.name}:\n{self._stderr_tail()}")
                if await self._healthy(base_url):
                    break
                await asyncio.sleep(0.4)
            else:
                await self._stop_owned()
                raise LlamaCppError(f"llama-server did not become ready within {self.START_TIMEOUT}s:\n{self._stderr_tail()}")

            self._running[entry.id] = (base_url, key)
            self._write_state(entry, base_url, key, self._proc.pid)
            logger.info("llama-server for %s on port %d (pid=%d)", entry.id, port, self._proc.pid)
            return base_url, key

    def _write_state(self, entry: ModelCatalogEntry, base_url: str, key: str, pid: int) -> None:
        try:
            self._state_dir.mkdir(parents=True, exist_ok=True)
            path = self._state_path(entry)
            tmp = path.with_suffix(".tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # holds the API key
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump({"base_url": base_url, "api_key": key, "pid": pid, "model": entry.id}, fh)
            os.replace(tmp, path)
        except OSError as exc:
            logger.warning("could not record llama-server state: %s", exc)

    def _spawn(self, coro: Any) -> None:
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _pump_stderr(self, proc: asyncio.subprocess.Process) -> None:
        assert proc.stderr is not None
        async for line in proc.stderr:  # also keeps the pipe drained so the server never blocks on a full buffer
            self._stderr.append(line.decode("utf-8", errors="replace").rstrip())

    def _stderr_tail(self) -> str:
        return "\n".join(list(self._stderr)[-15:]) or "(no output)"

    async def _stop_owned(self) -> None:
        proc, model = self._proc, self._owned_model
        self._proc, self._owned_model = None, None
        if model:
            self._running.pop(model, None)
            try:
                for p in self._state_dir.glob(f"llama-server.{re.sub(r'[^A-Za-z0-9._-]+', '_', model)}.json"):
                    p.unlink(missing_ok=True)
            except OSError:
                pass
        if proc is None or proc.returncode is not None:
            return
        try:
            if os.name == "posix":
                os.killpg(proc.pid, signal.SIGTERM)
            else:
                proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=self.STOP_TIMEOUT)
            except asyncio.TimeoutError:
                if os.name == "posix":
                    os.killpg(proc.pid, signal.SIGKILL)
                else:
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, check=False)
                await proc.wait()
        except (ProcessLookupError, PermissionError):
            pass

    async def stop(self) -> None:
        """Stop the server this process started (servers started by another process are left alone)."""
        async with self._lock:
            await self._stop_owned()
            self._running.clear()

    async def close(self) -> None:
        await self.stop()
        await self._http.aclose()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":  # os.kill(pid, 0) would terminate the process on Windows
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:  # Windows: invalid handle etc.
        return False
    return True
