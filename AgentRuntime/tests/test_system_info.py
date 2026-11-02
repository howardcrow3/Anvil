"""Tests for system info detection."""

import platform

from anvil_agent.services.system_info import SystemInfo, get_system_info


class TestSystemInfo:
    def test_returns_system_info(self):
        info = get_system_info()
        assert isinstance(info, SystemInfo)

    def test_total_ram_positive(self):
        info = get_system_info()
        assert info.total_ram_gb > 0

    def test_available_ram_positive(self):
        info = get_system_info()
        assert info.available_ram_gb > 0

    def test_cpu_cores_positive(self):
        info = get_system_info()
        assert info.cpu_cores > 0

    def test_metal_on_arm64_mac(self):
        info = get_system_info()
        if platform.machine() == "arm64" and platform.system() == "Darwin":
            assert info.has_metal is True

    def test_chip_detected(self):
        info = get_system_info()
        assert info.chip != ""

    def test_max_recommended_model_gb(self):
        info = get_system_info()
        assert info.max_recommended_model_gb > 0
        assert info.max_recommended_model_gb <= info.total_ram_gb


class TestDetectTotalRam:
    def test_linux_meminfo_parsed(self, monkeypatch):
        from anvil_agent.services import system_info as si

        monkeypatch.setattr(si.platform, "system", lambda: "Linux")
        monkeypatch.setattr(si, "_read_text", lambda path: "MemTotal:       32768000 kB\nMemFree: 1 kB\n")
        assert si.detect_total_ram_gb() == round(32768000 * 1024 / 2**30)

    def test_windows_uses_global_memory_status(self, monkeypatch):
        from anvil_agent.services import system_info as si

        monkeypatch.setattr(si.platform, "system", lambda: "Windows")
        monkeypatch.setattr(si, "_windows_total_bytes", lambda: 64 * 2**30 - 100_000_000)
        assert si.detect_total_ram_gb() == 64

    def test_unknown_returns_none(self, monkeypatch):
        from anvil_agent.services import system_info as si

        monkeypatch.setattr(si.platform, "system", lambda: "Linux")

        def boom(path):
            raise OSError("no /proc")

        monkeypatch.setattr(si, "_read_text", boom)
        assert si.detect_total_ram_gb() is None

    def test_legacy_fallback_is_8(self, monkeypatch):
        from anvil_agent.services import system_info as si

        monkeypatch.setattr(si, "detect_total_ram_gb", lambda: None)
        assert si._get_total_ram_gb() == 8
