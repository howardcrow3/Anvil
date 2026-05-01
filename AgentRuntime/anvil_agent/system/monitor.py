"""Performance monitoring for inference and system resources."""
from __future__ import annotations
import time
import subprocess
import logging
from collections import deque
from typing import Any

logger = logging.getLogger(__name__)

class PerformanceMonitor:
    """Track inference performance and system resource usage."""

    def __init__(self, history_size: int = 50) -> None:
        self._inference_history: deque[dict[str, Any]] = deque(maxlen=history_size)
        self._start_time: float | None = None
        self._start_tokens: int = 0

    def start_inference(self) -> None:
        """Mark the start of an inference request."""
        self._start_time = time.monotonic()
        self._start_tokens = 0

    def record_tokens(self, token_count: int) -> None:
        """Record tokens received during streaming."""
        self._start_tokens = token_count

    def end_inference(self, total_tokens: int | None = None) -> None:
        """Mark the end of an inference request and record stats."""
        if self._start_time is None:
            return
        elapsed = time.monotonic() - self._start_time
        tokens = total_tokens or self._start_tokens
        tps = tokens / elapsed if elapsed > 0 else 0
        self._inference_history.append({
            "tokens": tokens,
            "elapsed_sec": round(elapsed, 2),
            "tokens_per_sec": round(tps, 1),
            "timestamp": time.time(),
        })
        self._start_time = None

    def get_memory_pressure(self) -> dict[str, Any]:
        """Get current memory usage from macOS."""
        try:
            result = subprocess.run(
                ["memory_pressure"],
                capture_output=True, text=True, timeout=5
            )
            output = result.stdout
            # Parse "System-wide memory free percentage: XX%"
            for line in output.split("\n"):
                if "free percentage" in line.lower():
                    pct = int("".join(c for c in line.split(":")[-1] if c.isdigit()))
                    return {"free_pct": pct, "pressure": "normal" if pct > 20 else ("warning" if pct > 5 else "critical")}
        except Exception:
            pass
        return {"free_pct": -1, "pressure": "unknown"}

    def get_inference_stats(self) -> dict[str, Any]:
        """Get summary of recent inference performance."""
        if not self._inference_history:
            return {"count": 0, "avg_tokens_per_sec": 0, "avg_elapsed_sec": 0}

        entries = list(self._inference_history)
        avg_tps = sum(e["tokens_per_sec"] for e in entries) / len(entries)
        avg_elapsed = sum(e["elapsed_sec"] for e in entries) / len(entries)

        return {
            "count": len(entries),
            "avg_tokens_per_sec": round(avg_tps, 1),
            "avg_elapsed_sec": round(avg_elapsed, 2),
            "last": entries[-1] if entries else None,
        }

    def get_stats(self) -> dict[str, Any]:
        """Get combined system + inference stats."""
        return {
            "memory": self.get_memory_pressure(),
            "inference": self.get_inference_stats(),
        }
