"""Tool-call loop guardrails.

Adapted from Hermes Agent's ``agent/tool_guardrails.py`` (MIT, Nous Research; see
THIRD_PARTY_NOTICES.md). Side-effect free: the controller tracks per-turn tool-call
observations and returns decisions; the agent loop decides how to surface them.
Warnings ride on the tool result text, so message-role alternation is never disturbed.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping

# Re-reading or re-searching with identical args and an identical result is a stall.
IDEMPOTENT_TOOLS = frozenset({"read_file", "glob", "grep", "web_search", "web_fetch", "session_search"})
# A failure here is normal work output (red test run, empty grep), not a sign of a loop.
FAILURE_TOLERANT_TOOLS = frozenset({"bash"})
# A successful call to one of these means the next retry is a new experiment, not a replay.
PROGRESS_RESET_TOOLS = frozenset({"write_file", "edit_file", "bash"})


def canonical_args(args: Mapping[str, Any] | None) -> str:
    return json.dumps(args or {}, sort_keys=True, separators=(",", ":"), default=str)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:16]


@dataclass(frozen=True)
class GuardConfig:
    exact_failure_warn_after: int = 2
    exact_failure_block_after: int = 5
    same_tool_failure_warn_after: int = 3
    same_tool_failure_halt_after: int = 8
    no_progress_warn_after: int = 2
    no_progress_block_after: int = 5
    identical_call_notice_after: int = 3
    max_web_searches_per_turn: int = 50
    # Interactive sessions warn only; unattended ones (gateway, scheduled) hard-stop.
    hard_stop: bool = False


@dataclass(frozen=True)
class GuardDecision:
    action: str = "allow"  # allow | warn | block | halt
    code: str = "allow"
    message: str = ""

    @property
    def allows_execution(self) -> bool:
        return self.action in ("allow", "warn")

    @property
    def should_halt(self) -> bool:
        return self.action in ("block", "halt")


ALLOW = GuardDecision()


@dataclass
class ToolLoopGuard:
    """Per-turn tool-call loop detector. Call :meth:`reset` at the start of each run."""

    config: GuardConfig = field(default_factory=GuardConfig)
    _exact_failures: dict[str, int] = field(default_factory=dict)
    _tool_failures: dict[str, int] = field(default_factory=dict)
    _no_progress: dict[str, tuple[str, int]] = field(default_factory=dict)
    _last_sig: str | None = None
    _streak: int = 0
    _searches: int = 0

    def reset(self) -> None:
        self._exact_failures.clear()
        self._tool_failures.clear()
        self._no_progress.clear()
        self._last_sig = None
        self._streak = 0
        self._searches = 0

    @staticmethod
    def signature(name: str, args: Mapping[str, Any] | None) -> str:
        return f"{name}:{_sha(canonical_args(args))}"

    def before_call(self, name: str, args: Mapping[str, Any] | None) -> GuardDecision:
        """Decide whether a call may run. Blocks replays that already failed or stalled too often."""
        cfg = self.config
        if name == "web_search" and cfg.max_web_searches_per_turn:
            if self._searches >= cfg.max_web_searches_per_turn:
                return GuardDecision(
                    "halt", "web_search_cap",
                    f"web_search call cap ({cfg.max_web_searches_per_turn}) reached this turn; answer from what you have.",
                )
        if not cfg.hard_stop:
            return ALLOW
        sig = self.signature(name, args)
        failures = self._exact_failures.get(sig, 0)
        if failures >= cfg.exact_failure_block_after and name not in FAILURE_TOLERANT_TOOLS:
            return GuardDecision(
                "block", "exact_failure_block",
                f"Blocked: {name} with these exact arguments has failed {failures} times. Change approach.",
            )
        _, repeats = self._no_progress.get(sig, ("", 0))
        if repeats >= cfg.no_progress_block_after:
            return GuardDecision(
                "block", "no_progress_block",
                f"Blocked: {name} returned the identical result {repeats} times. The state has not changed; do something different.",
            )
        return ALLOW

    def after_call(
        self, name: str, args: Mapping[str, Any] | None, content: str, is_error: bool
    ) -> GuardDecision:
        """Record an executed call; return a warn/halt decision whose message is appended to the result."""
        cfg = self.config
        sig = self.signature(name, args)
        if name == "web_search":
            self._searches += 1

        if self._last_sig == sig:
            self._streak += 1
        else:
            self._last_sig, self._streak = sig, 1

        if is_error:
            self._exact_failures[sig] = self._exact_failures.get(sig, 0) + 1
            self._tool_failures[name] = self._tool_failures.get(name, 0) + 1
        elif name in PROGRESS_RESET_TOOLS:
            self._exact_failures.clear()
            self._tool_failures.clear()
            self._no_progress.clear()

        if is_error and name not in FAILURE_TOLERANT_TOOLS:
            exact = self._exact_failures[sig]
            if cfg.hard_stop and exact >= cfg.exact_failure_block_after:
                return GuardDecision("halt", "exact_failure_halt", f"{name} failed {exact} times with identical arguments; stopping.")
            if exact >= cfg.exact_failure_warn_after:
                return GuardDecision(
                    "warn", "exact_failure_warn",
                    f"[guard] {name} has failed {exact} times with these exact arguments. Try a different approach.",
                )
            same_tool = self._tool_failures[name]
            if cfg.hard_stop and same_tool >= cfg.same_tool_failure_halt_after:
                return GuardDecision("halt", "same_tool_halt", f"{name} failed {same_tool} times this turn; stopping.")
            if same_tool >= cfg.same_tool_failure_warn_after:
                return GuardDecision(
                    "warn", "same_tool_warn",
                    f"[guard] {name} has failed {same_tool} times this turn. Reconsider the approach.",
                )

        if not is_error and name in IDEMPOTENT_TOOLS:
            rhash = _sha(content)
            prev_hash, count = self._no_progress.get(sig, ("", 0))
            count = count + 1 if prev_hash == rhash else 1
            self._no_progress[sig] = (rhash, count)
            if count >= cfg.no_progress_warn_after:
                return GuardDecision(
                    "warn", "no_progress_warn",
                    f"[guard] {name} returned the identical result {count} times. Nothing has changed; act on it or try something else.",
                )

        if self._streak >= cfg.identical_call_notice_after and name != "ask_user":
            return GuardDecision(
                "warn", "identical_call",
                f"[guard] {name} has now been called {self._streak} times in a row with identical arguments.",
            )
        return ALLOW
