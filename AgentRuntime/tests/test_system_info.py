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
