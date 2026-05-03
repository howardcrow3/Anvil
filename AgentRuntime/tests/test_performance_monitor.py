"""Tests for the performance monitor."""

import time

from anvil_agent.system.monitor import PerformanceMonitor


class TestPerformanceMonitor:
    def test_empty_stats(self):
        mon = PerformanceMonitor()
        stats = mon.get_inference_stats()
        assert stats["count"] == 0
        assert stats["avg_tokens_per_sec"] == 0

    def test_record_inference(self):
        mon = PerformanceMonitor()
        mon.start_inference()
        time.sleep(0.05)
        mon.end_inference(total_tokens=100)
        stats = mon.get_inference_stats()
        assert stats["count"] == 1
        assert stats["avg_tokens_per_sec"] > 0
        assert stats["last"] is not None
        assert stats["last"]["tokens"] == 100

    def test_multiple_inferences(self):
        mon = PerformanceMonitor()
        for i in range(3):
            mon.start_inference()
            mon.end_inference(total_tokens=50)
        stats = mon.get_inference_stats()
        assert stats["count"] == 3

    def test_end_without_start_noop(self):
        mon = PerformanceMonitor()
        mon.end_inference(total_tokens=10)
        assert mon.get_inference_stats()["count"] == 0

    def test_history_limit(self):
        mon = PerformanceMonitor(history_size=5)
        for i in range(10):
            mon.start_inference()
            mon.end_inference(total_tokens=10)
        stats = mon.get_inference_stats()
        assert stats["count"] == 5

    def test_get_stats_combined(self):
        mon = PerformanceMonitor()
        stats = mon.get_stats()
        assert "memory" in stats
        assert "inference" in stats

    def test_record_tokens(self):
        mon = PerformanceMonitor()
        mon.start_inference()
        mon.record_tokens(42)
        mon.end_inference()
        stats = mon.get_inference_stats()
        assert stats["last"]["tokens"] == 42
