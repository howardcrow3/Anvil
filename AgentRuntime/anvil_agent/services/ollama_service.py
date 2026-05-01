"""Ollama inference server lifecycle manager."""

from __future__ import annotations

import asyncio
import logging
import shutil
import signal
from typing import Any, Callable

import httpx
from pydantic import BaseModel

from anvil_agent.services.system_info import SystemInfo, get_system_info

logger = logging.getLogger(__name__)


class LocalModel(BaseModel):
    """A model downloaded locally in Ollama."""

    name: str
    size_bytes: int
    digest: str
    modified_at: str
    parameter_size: str = ""
    quantization: str = ""


class OllamaService:
    """Manages the Ollama inference server lifecycle."""

    BUNDLED_PATH = "ollama"
    DEFAULT_PORT = 11434
    FALLBACK_PORT = 11435
    BASE_URL_TEMPLATE = "http://localhost:{port}"
    STARTUP_TIMEOUT = 30  # seconds
    SHUTDOWN_TIMEOUT = 10  # seconds

    def __init__(self) -> None:
        self._process: asyncio.subprocess.Process | None = None
        self._port: int = self.DEFAULT_PORT
        self._base_url: str = self.BASE_URL_TEMPLATE.format(port=self._port)
        self._client: httpx.AsyncClient = httpx.AsyncClient(timeout=30.0)
        self._managed: bool = False  # True if we started the process

    @property
    def port(self) -> int:
        return self._port

    @property
    def base_url(self) -> str:
        return self._base_url

    # ── Lifecycle ──────────────────────────────────────────────────

    async def start(self) -> bool:
        """Start Ollama server. Detect port conflicts, use fallback if needed.

        Returns True if the server is running (either started by us or already running).
        """
        # Check if already running on default port
        if await self._check_port(self.DEFAULT_PORT):
            self._port = self.DEFAULT_PORT
            self._base_url = self.BASE_URL_TEMPLATE.format(port=self._port)
            logger.info("Ollama already running on port %d", self._port)
            return True

        # Find the binary
        binary = self._resolve_binary()
        if binary is None:
            logger.error("Ollama binary not found")
            return False

        # Try default port first, fallback if occupied
        for port in (self.DEFAULT_PORT, self.FALLBACK_PORT):
            if await self._is_port_in_use(port):
                logger.info("Port %d in use, trying next", port)
                continue

            self._port = port
            self._base_url = self.BASE_URL_TEMPLATE.format(port=port)

            env = {"OLLAMA_HOST": f"0.0.0.0:{port}"}
            try:
                self._process = await asyncio.create_subprocess_exec(
                    binary,
                    "serve",
                    env=env,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                self._managed = True
            except OSError as exc:
                logger.error("Failed to start Ollama: %s", exc)
                return False

            # Wait for it to become ready
            if await self._wait_for_ready():
                logger.info("Ollama started on port %d (pid=%d)", port, self._process.pid)
                return True
            else:
                logger.error("Ollama failed to become ready on port %d", port)
                await self.stop()

        return False

    async def stop(self) -> None:
        """Gracefully stop the managed Ollama server."""
        if self._process is None or not self._managed:
            return

        try:
            self._process.send_signal(signal.SIGTERM)
            try:
                await asyncio.wait_for(
                    self._process.wait(), timeout=self.SHUTDOWN_TIMEOUT
                )
            except asyncio.TimeoutError:
                logger.warning("Ollama did not stop gracefully, killing")
                self._process.kill()
                await self._process.wait()
        except ProcessLookupError:
            pass  # Already exited
        finally:
            self._process = None
            self._managed = False

    async def is_running(self) -> bool:
        """Check if Ollama is responding on the current port."""
        return await self._check_port(self._port)

    async def health_check(self) -> dict[str, Any]:
        """Full health check with version info."""
        try:
            resp = await self._client.get(f"{self._base_url}/api/version")
            resp.raise_for_status()
            version_data = resp.json()
        except (httpx.HTTPError, Exception):
            return {"healthy": False, "error": "Ollama not reachable"}

        system = get_system_info()

        return {
            "healthy": True,
            "port": self._port,
            "version": version_data.get("version", "unknown"),
            "managed": self._managed,
            "system": {
                "chip": system.chip,
                "ram_gb": system.total_ram_gb,
                "has_metal": system.has_metal,
            },
        }

    # ── Model Operations ───────────────────────────────────────────

    async def list_models(self) -> list[LocalModel]:
        """List all downloaded models."""
        try:
            resp = await self._client.get(f"{self._base_url}/api/tags")
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, Exception) as exc:
            logger.error("Failed to list models: %s", exc)
            return []

        models: list[LocalModel] = []
        for m in data.get("models", []):
            details = m.get("details", {})
            models.append(
                LocalModel(
                    name=m["name"],
                    size_bytes=m.get("size", 0),
                    digest=m.get("digest", ""),
                    modified_at=m.get("modified_at", ""),
                    parameter_size=details.get("parameter_size", ""),
                    quantization=details.get("quantization_level", ""),
                )
            )
        return models

    async def pull_model(
        self,
        model_name: str,
        progress_callback: Callable[[str, int, int], None] | None = None,
    ) -> bool:
        """Pull/download a model with progress reporting.

        progress_callback receives (status, completed_bytes, total_bytes).
        """
        try:
            async with self._client.stream(
                "POST",
                f"{self._base_url}/api/pull",
                json={"name": model_name, "stream": True},
                timeout=None,
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    import json as _json

                    try:
                        chunk = _json.loads(line)
                    except _json.JSONDecodeError:
                        continue

                    status = chunk.get("status", "")
                    completed = chunk.get("completed", 0)
                    total = chunk.get("total", 0)

                    if progress_callback is not None:
                        progress_callback(status, completed, total)

                    if chunk.get("error"):
                        logger.error("Pull error: %s", chunk["error"])
                        return False

            return True
        except (httpx.HTTPError, Exception) as exc:
            logger.error("Failed to pull model %s: %s", model_name, exc)
            return False

    async def delete_model(self, model_name: str) -> bool:
        """Delete a downloaded model."""
        try:
            resp = await self._client.request(
                "DELETE",
                f"{self._base_url}/api/delete",
                json={"name": model_name},
            )
            resp.raise_for_status()
            return True
        except (httpx.HTTPError, Exception) as exc:
            logger.error("Failed to delete model %s: %s", model_name, exc)
            return False

    async def get_model_info(self, model_name: str) -> dict[str, Any]:
        """Get detailed info about a model (size, quantization, etc.)."""
        try:
            resp = await self._client.post(
                f"{self._base_url}/api/show",
                json={"name": model_name},
            )
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPError, Exception) as exc:
            logger.error("Failed to get info for %s: %s", model_name, exc)
            return {"error": str(exc)}

    # ── Discovery ──────────────────────────────────────────────────

    def detect_existing_ollama(self) -> str | None:
        """Check if the user has Ollama installed system-wide."""
        path = shutil.which("ollama")
        if path:
            logger.info("Found system Ollama at %s", path)
        return path

    def get_system_info(self) -> SystemInfo:
        """Detect RAM, GPU (Metal), and recommend models."""
        return get_system_info()

    # ── Internal Helpers ───────────────────────────────────────────

    def _resolve_binary(self) -> str | None:
        """Find the Ollama binary: bundled first, then system PATH."""
        # In production the bundled binary would be in the app bundle.
        # For now, fall back to system-installed Ollama.
        return shutil.which("ollama")

    async def _check_port(self, port: int) -> bool:
        """Check if Ollama is responding on a given port."""
        try:
            url = self.BASE_URL_TEMPLATE.format(port=port)
            resp = await self._client.get(url, timeout=3.0)
            return resp.status_code == 200
        except (httpx.HTTPError, Exception):
            return False

    async def _is_port_in_use(self, port: int) -> bool:
        """Check if a port is already bound (but not by Ollama)."""
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection("127.0.0.1", port), timeout=1.0
            )
            writer.close()
            await writer.wait_closed()
            return True
        except (OSError, asyncio.TimeoutError):
            return False

    async def _wait_for_ready(self) -> bool:
        """Poll until Ollama responds or timeout."""
        for _ in range(self.STARTUP_TIMEOUT * 2):  # Check every 0.5s
            if await self._check_port(self._port):
                return True
            await asyncio.sleep(0.5)
        return False

    async def close(self) -> None:
        """Cleanup: stop server and close HTTP client."""
        await self.stop()
        await self._client.aclose()
