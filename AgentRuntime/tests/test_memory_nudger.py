"""Tests for anvil_agent.memory.nudger."""

from __future__ import annotations

from anvil_agent.memory.nudger import NUDGE_TEXT, MemoryNudger


class TestMemoryNudger:
    """Tests for MemoryNudger."""

    def test_no_nudge_before_interval(self):
        nudger = MemoryNudger()
        for turn in range(1, 10):
            assert nudger.check_nudge(turn) is None

    def test_nudge_at_interval(self):
        nudger = MemoryNudger()
        assert nudger.check_nudge(10) == NUDGE_TEXT

    def test_nudge_at_multiples(self):
        nudger = MemoryNudger()
        assert nudger.check_nudge(10) == NUDGE_TEXT
        assert nudger.check_nudge(20) == NUDGE_TEXT
        assert nudger.check_nudge(30) == NUDGE_TEXT

    def test_max_nudges_respected(self):
        nudger = MemoryNudger()
        nudger.check_nudge(10)
        nudger.check_nudge(20)
        nudger.check_nudge(30)
        assert nudger.check_nudge(40) is None
        assert nudger.check_nudge(50) is None

    def test_nudge_at_zero(self):
        nudger = MemoryNudger()
        assert nudger.check_nudge(0) is None

    def test_custom_interval(self):
        nudger = MemoryNudger(interval=5)
        assert nudger.check_nudge(4) is None
        assert nudger.check_nudge(5) == NUDGE_TEXT

    def test_custom_max_nudges(self):
        nudger = MemoryNudger(max_nudges=1)
        assert nudger.check_nudge(10) == NUDGE_TEXT
        assert nudger.check_nudge(20) is None

    def test_reset(self):
        nudger = MemoryNudger()
        nudger.check_nudge(10)
        nudger.check_nudge(20)
        nudger.check_nudge(30)
        assert nudger.check_nudge(40) is None
        nudger.reset()
        assert nudger.check_nudge(10) == NUDGE_TEXT

    def test_nudge_text_content(self):
        nudger = MemoryNudger()
        result = nudger.check_nudge(10)
        assert result == NUDGE_TEXT
        assert "save it to memory" in result
