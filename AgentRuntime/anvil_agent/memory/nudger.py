"""Memory nudger - periodically reminds the agent to save learnings."""

from __future__ import annotations

NUDGE_TEXT = (
    "If you've learned anything important about the user, their project, "
    "or useful patterns during this conversation, save it to memory now."
)


class MemoryNudger:
    """Periodically injects a nudge to save memory during long conversations."""

    def __init__(self, interval: int = 10, max_nudges: int = 3) -> None:
        self._interval = interval
        self._max_nudges = max_nudges
        self._nudges_given = 0

    def check_nudge(self, turn_count: int) -> str | None:
        """Return nudge text if it's time, else None."""
        if self._nudges_given >= self._max_nudges:
            return None
        if turn_count > 0 and turn_count % self._interval == 0:
            self._nudges_given += 1
            return NUDGE_TEXT
        return None

    def reset(self) -> None:
        """Reset for a new session."""
        self._nudges_given = 0
