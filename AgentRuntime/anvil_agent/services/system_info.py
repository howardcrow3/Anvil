"""Apple Silicon hardware detection and model recommendations."""

from __future__ import annotations

import asyncio
import platform
import subprocess

from pydantic import BaseModel


class SystemInfo(BaseModel):
    """Detected system hardware capabilities."""

    chip: str  # e.g. "Apple M3 Pro"
    chip_family: str  # e.g. "M3"
    total_ram_gb: int
    available_ram_gb: int
    has_metal: bool
    cpu_cores: int
    max_recommended_model_gb: int  # Largest model RAM we'd recommend


def get_system_info() -> SystemInfo:
    """Detect Apple Silicon hardware capabilities."""
    chip = _detect_chip()
    chip_family = _parse_chip_family(chip)
    total_ram_gb = _get_total_ram_gb()
    available_ram_gb = _get_available_ram_gb()
    cpu_cores = _get_cpu_cores()
    has_metal = _check_metal()
    max_model_gb = _recommend_max_model_gb(total_ram_gb)

    return SystemInfo(
        chip=chip,
        chip_family=chip_family,
        total_ram_gb=total_ram_gb,
        available_ram_gb=available_ram_gb,
        has_metal=has_metal,
        cpu_cores=cpu_cores,
        max_recommended_model_gb=max_model_gb,
    )


def _detect_chip() -> str:
    """Get the chip name via sysctl."""
    try:
        result = subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else "Unknown"
    except Exception:
        return "Unknown"


def _parse_chip_family(chip: str) -> str:
    """Extract chip family (M1, M2, M3, M4) from brand string."""
    chip_lower = chip.lower()
    for family in ("m4", "m3", "m2", "m1"):
        if family in chip_lower:
            return family.upper()
    return "Unknown"


def _get_total_ram_gb() -> int:
    """Get total physical RAM in GB."""
    try:
        result = subprocess.run(
            ["sysctl", "-n", "hw.memsize"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return int(result.stdout.strip()) // (1024 ** 3)
    except Exception:
        pass
    return 8  # Safe fallback


def _get_available_ram_gb() -> int:
    """Estimate available RAM using vm_stat."""
    try:
        result = subprocess.run(
            ["vm_stat"], capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0:
            return _get_total_ram_gb() // 2

        pages_free = 0
        pages_inactive = 0
        page_size = 16384  # Apple Silicon default

        for line in result.stdout.splitlines():
            if "page size of" in line:
                page_size = int(line.split()[-2])
            elif "Pages free" in line:
                pages_free = int(line.split()[-1].rstrip("."))
            elif "Pages inactive" in line:
                pages_inactive = int(line.split()[-1].rstrip("."))

        available_bytes = (pages_free + pages_inactive) * page_size
        return max(1, available_bytes // (1024 ** 3))
    except Exception:
        return _get_total_ram_gb() // 2


def _get_cpu_cores() -> int:
    """Get total CPU core count."""
    try:
        result = subprocess.run(
            ["sysctl", "-n", "hw.ncpu"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return int(result.stdout.strip())
    except Exception:
        pass
    return 8


def _check_metal() -> bool:
    """Check if Metal GPU is available (always true on Apple Silicon)."""
    return platform.machine() == "arm64" and platform.system() == "Darwin"


def _recommend_max_model_gb(total_ram_gb: int) -> int:
    """Recommend max model size based on available RAM.

    Rule of thumb: model should use at most ~75% of total RAM
    to leave room for the OS, Ollama overhead, and the app itself.
    """
    return max(2, int(total_ram_gb * 0.75))
