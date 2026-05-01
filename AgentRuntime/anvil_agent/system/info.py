"""System information detection for macOS Apple Silicon."""
from __future__ import annotations
import json
import subprocess
import logging
from typing import Any

logger = logging.getLogger(__name__)

def get_system_info() -> dict[str, Any]:
    """Detect system capabilities: RAM, chip, GPU cores."""
    info: dict[str, Any] = {}

    # Total RAM
    try:
        result = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5)
        mem_bytes = int(result.stdout.strip())
        info["total_ram_gb"] = round(mem_bytes / (1024**3), 1)
    except Exception:
        info["total_ram_gb"] = 0

    # Available RAM
    try:
        result = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=5)
        # Parse vm_stat output for free + inactive pages
        lines = result.stdout.strip().split("\n")
        page_size = 16384  # Apple Silicon default
        free_pages = 0
        for line in lines:
            if "Pages free:" in line:
                free_pages += int(line.split(":")[1].strip().rstrip("."))
            elif "Pages inactive:" in line:
                free_pages += int(line.split(":")[1].strip().rstrip("."))
        info["available_ram_gb"] = round(free_pages * page_size / (1024**3), 1)
    except Exception:
        info["available_ram_gb"] = 0

    # Chip name
    try:
        result = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True, timeout=5)
        info["chip"] = result.stdout.strip()
    except Exception:
        info["chip"] = "Unknown"

    # GPU info via system_profiler
    try:
        result = subprocess.run(
            ["system_profiler", "SPDisplaysDataType", "-json"],
            capture_output=True, text=True, timeout=10
        )
        gpu_data = json.loads(result.stdout)
        displays = gpu_data.get("SPDisplaysDataType", [])
        if displays:
            gpu = displays[0]
            info["gpu_name"] = gpu.get("sppci_model", "Unknown")
            info["gpu_cores"] = gpu.get("sppci_cores", "Unknown")
            info["metal_family"] = gpu.get("spdisplays_metal", "Unknown")
    except Exception:
        info["gpu_name"] = "Unknown"
        info["gpu_cores"] = "Unknown"
        info["metal_family"] = "Unknown"

    return info

def recommend_models(available_ram_gb: float) -> list[dict[str, Any]]:
    """Return list of models that fit in available RAM with comfort margin."""
    # Load model catalog
    from pathlib import Path
    catalog_path = Path(__file__).parent.parent.parent.parent / "Resources" / "default-models.json"
    if not catalog_path.exists():
        # Fallback to bundled location
        catalog_path = Path(__file__).parent.parent / "resources" / "default-models.json"

    models = []
    if catalog_path.exists():
        try:
            models = json.loads(catalog_path.read_text())
        except Exception:
            pass

    # Filter models that fit (need ~2GB overhead for OS + app)
    usable_ram = available_ram_gb - 2.0
    recommended = []
    for model in models:
        min_ram = model.get("min_ram_gb", 0)
        fits = min_ram <= usable_ram
        recommended.append({
            **model,
            "fits_in_ram": fits,
            "comfort": "comfortable" if usable_ram >= min_ram * 1.3 else ("tight" if fits else "insufficient"),
        })

    return sorted(recommended, key=lambda m: (not m["fits_in_ram"], m.get("min_ram_gb", 0)))
