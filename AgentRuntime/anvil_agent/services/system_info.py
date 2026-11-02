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


def _read_text(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _linux_total_bytes() -> int:
    for line in _read_text("/proc/meminfo").splitlines():
        if line.startswith("MemTotal:"):
            return int(line.split()[1]) * 1024  # reported in kB
    raise ValueError("MemTotal not found")


def _windows_total_bytes() -> int:
    import ctypes

    class MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = MemoryStatus()
    status.dwLength = ctypes.sizeof(MemoryStatus)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):  # type: ignore[attr-defined]
        raise OSError("GlobalMemoryStatusEx failed")
    return int(status.ullTotalPhys)


def _macos_total_bytes() -> int:
    result = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5)
    if result.returncode != 0:
        raise OSError("sysctl hw.memsize failed")
    return int(result.stdout.strip())


def detect_total_ram_gb() -> int | None:
    """Total physical RAM in GB (rounded to the nearest GB), or None if it cannot be determined."""
    reader = {"Linux": _linux_total_bytes, "Windows": _windows_total_bytes, "Darwin": _macos_total_bytes}.get(platform.system())
    if reader is None:
        return None
    try:
        return round(reader() / 2**30)
    except Exception:
        return None


def _get_total_ram_gb() -> int:
    """Total physical RAM in GB; 8 if it cannot be detected."""
    return detect_total_ram_gb() or 8


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
    to leave room for the OS, llama.cpp overhead, and the app itself.
    """
    return max(2, int(total_ram_gb * 0.75))
