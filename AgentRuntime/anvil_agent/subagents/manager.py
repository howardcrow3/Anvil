"""Subagent lifecycle manager.

Modeled on Hermes Agent's delegation layer (``tools/delegate_tool*.py``, ``agent/subagent_lifecycle.py``;
MIT, Nous Research — see THIRD_PARTY_NOTICES.md): a parent hands a goal to a child agent loop, which
runs in the background or is awaited. While it runs the parent (or the UI) can list it, ``steer`` it
with a course correction, or ``stop`` it. Finished background children are reported back to their
parent through a tool-result annotation, never a new message row.
"""

from __future__ import annotations

import asyncio
import enum
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from anvil_agent.context import current_agent_env
from anvil_agent.models.types import ChatMessage

logger = logging.getLogger(__name__)

TERMINAL_RETENTION_SECONDS = 3600
# Children never get the delegation surface themselves (depth is capped anyway).
DELEGATION_TOOLS = ("delegate_task",)
_MAX_LOG = 200


class SubagentError(ValueError):
    pass


class SubagentState(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def terminal(self) -> bool:
        return self in (SubagentState.SUCCEEDED, SubagentState.FAILED, SubagentState.CANCELLED)


@dataclass
class SubagentSpec:
    goal: str
    context: str = ""
    role: str = "worker"
    model: str | None = None
    allowed_tools: list[str] | None = None
    blocked_tools: tuple[str, ...] = DELEGATION_TOOLS
    max_iterations: int = 40
    timeout_seconds: float | None = None
    env: dict[str, Any] = field(default_factory=dict)


@dataclass
class SubagentRecord:
    id: str
    goal: str
    role: str
    parent_id: str | None
    depth: int
    model: str | None
    state: SubagentState = SubagentState.PENDING
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None
    summary: str = ""
    error: str | None = None
    tool_calls: int = 0
    steers: list[str] = field(default_factory=list)
    log: list[dict[str, Any]] = field(default_factory=list)
    delivered: bool = False

    def to_dict(self, include_log: bool = False) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id, "goal": self.goal[:200], "role": self.role, "parent_id": self.parent_id,
            "depth": self.depth, "model": self.model, "state": self.state.value,
            "created_at": self.created_at, "started_at": self.started_at, "completed_at": self.completed_at,
            "elapsed": round((self.completed_at or time.time()) - (self.started_at or self.created_at), 1),
            "tool_calls": self.tool_calls, "summary": self.summary, "error": self.error, "steers": len(self.steers),
        }
        if include_log:
            d["log"] = list(self.log)
        return d


class NonInteractivePermissions:
    """Permission wrapper for unattended children: read-only tools pass, anything needing approval is denied."""

    def __init__(self, parent: Any, extra_allow: set[str] | None = None) -> None:
        self._parent = parent
        self._extra = set(extra_allow or ())

    def check_sync(self, tool_name: str) -> str:
        from anvil_agent.permissions import READ_ONLY_TOOLS

        decision = self._parent.check_sync(tool_name) if self._parent else "ask"
        if decision == "ask":
            return "allow" if tool_name in READ_ONLY_TOOLS or tool_name in self._extra else "deny"
        return decision

    async def request_permission(self, *_: Any, **__: Any) -> bool:
        return False


EventSink = Callable[[str, dict[str, Any]], Awaitable[None] | None]


class SubagentManager:
    """Runs child agent loops. ``loop_factory(spec)`` must return a ready ``AgentLoop``."""

    def __init__(
        self,
        loop_factory: Callable[[SubagentSpec], Any],
        max_concurrent: int = 4,
        max_depth: int = 1,
        on_event: EventSink | None = None,
    ) -> None:
        self._factory = loop_factory
        self._sem = asyncio.Semaphore(max_concurrent)
        self._max_depth = max_depth
        self._on_event = on_event
        self._records: dict[str, SubagentRecord] = {}
        self._loops: dict[str, Any] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._done: dict[str, asyncio.Event] = {}

    # -- spawning -------------------------------------------------------------

    async def spawn(self, spec: SubagentSpec, parent_id: str | None = None) -> SubagentRecord:
        if not spec.goal.strip():
            raise SubagentError("goal is required")
        parent = self._records.get(parent_id or "")
        depth = (parent.depth + 1) if parent else 1
        if depth > self._max_depth:
            raise SubagentError(f"subagents cannot spawn subagents (max depth {self._max_depth})")
        self._prune()
        rec = SubagentRecord(
            id=f"sa_{uuid.uuid4().hex[:8]}", goal=spec.goal, role=spec.role,
            parent_id=parent_id, depth=depth, model=spec.model,
        )
        self._records[rec.id] = rec
        self._done[rec.id] = asyncio.Event()
        self._tasks[rec.id] = asyncio.create_task(self._run(rec, spec))
        await self._emit("subagent.update", rec.to_dict())
        return rec

    async def _run(self, rec: SubagentRecord, spec: SubagentSpec) -> None:
        try:
            async with self._sem:
                if rec.state is SubagentState.CANCELLED:
                    return
                rec.state, rec.started_at = SubagentState.RUNNING, time.time()
                await self._emit("subagent.update", rec.to_dict())
                loop = self._factory(spec)
                loop.agent_id = rec.id
                self._loops[rec.id] = loop
                current_agent_env.set(dict(spec.env))
                await asyncio.wait_for(self._drive(rec, spec, loop), spec.timeout_seconds)
                if rec.state is SubagentState.RUNNING:
                    rec.state = SubagentState.SUCCEEDED
        except asyncio.TimeoutError:
            loop = self._loops.get(rec.id)
            if loop:
                loop.cancel()
            rec.state, rec.error = SubagentState.FAILED, f"timed out after {spec.timeout_seconds}s"
        except asyncio.CancelledError:
            rec.state = SubagentState.CANCELLED
        except Exception as exc:  # noqa: BLE001 - a child crash must never take the parent down
            logger.exception("Subagent %s crashed", rec.id)
            rec.state, rec.error = SubagentState.FAILED, str(exc)
        finally:
            rec.completed_at = time.time()
            self._loops.pop(rec.id, None)
            self._done[rec.id].set()
            await self._emit("subagent.update", rec.to_dict())

    async def _drive(self, rec: SubagentRecord, spec: SubagentSpec, loop: Any) -> None:
        prompt = spec.goal.strip()
        if spec.context.strip():
            prompt += f"\n\nContext:\n{spec.context.strip()}"
        prompt += (
            "\n\nWork autonomously. When finished, reply with a concise summary of the outcome: "
            "what you did, what you found, and anything the requester must know."
        )
        text = ""
        async for event in loop.run([ChatMessage(role="user", content=prompt)]):
            kind = event.get("type")
            if kind == "text_delta":
                text += event.get("text", "")
            elif kind == "tool_call":
                rec.tool_calls += 1
                self._log(rec, {"t": "call", "name": event.get("name"), "args": str(event.get("arguments"))[:160]})
            elif kind == "tool_result":
                # Everything said before a tool result was narration ("Let me check..."); only the text
                # after the last tool result is the final message the parent should receive.
                text = ""
                self._log(rec, {"t": "result", "error": bool(event.get("is_error")), "preview": str(event.get("content"))[:160]})
            elif kind == "error":
                rec.error = event.get("message")
                rec.state = SubagentState.FAILED
            elif kind == "done":
                reason = event.get("stop_reason")
                if reason == "cancelled":
                    rec.state = SubagentState.CANCELLED
                elif reason == "tool_loop_halt":
                    rec.state, rec.error = SubagentState.FAILED, event.get("message") or "tool loop halted"
            elif kind == "permission_request":
                await self._emit("subagent.permission_request", {"subagent_id": rec.id, "role": rec.role, "goal": rec.goal[:80], **event})
        rec.summary = text.strip()

    # -- control --------------------------------------------------------------

    def steer(self, subagent_id: str, message: str) -> bool:
        """Queue a course correction. Returns False if the child is unknown or already finished."""
        rec, loop = self._records.get(subagent_id), self._loops.get(subagent_id)
        if rec is None or loop is None or rec.state.terminal or not message.strip():
            return False
        loop.steer(message.strip())
        rec.steers.append(message.strip())
        return True

    async def stop(self, subagent_id: str, grace: float = 3.0) -> dict[str, Any]:
        rec = self._records.get(subagent_id)
        if rec is None:
            return {"accepted": False, "reason": "unknown subagent"}
        if rec.state.terminal:
            return {"accepted": False, "already_terminal": True, "state": rec.state.value}
        if rec.state is SubagentState.PENDING:
            rec.state = SubagentState.CANCELLED
        loop = self._loops.get(subagent_id)
        if loop:
            loop.cancel()
        done = self._done[subagent_id]
        try:
            await asyncio.wait_for(done.wait(), grace)
        except asyncio.TimeoutError:
            task = self._tasks.get(subagent_id)
            if task:
                task.cancel()
            await done.wait()
        return {"accepted": True, "state": rec.state.value}

    async def stop_all(self, parent_id: str | None = None) -> int:
        ids = [r.id for r in self._records.values() if not r.state.terminal and (parent_id is None or r.parent_id == parent_id)]
        for sid in ids:
            await self.stop(sid)
        return len(ids)

    async def wait(self, subagent_id: str, timeout: float | None = None) -> SubagentRecord:
        rec = self._records.get(subagent_id)
        if rec is None:
            raise SubagentError(f"unknown subagent '{subagent_id}'")
        try:
            await asyncio.wait_for(self._done[subagent_id].wait(), timeout)
        except asyncio.TimeoutError:
            pass
        return rec

    # -- queries --------------------------------------------------------------

    def get(self, subagent_id: str) -> SubagentRecord | None:
        return self._records.get(subagent_id)

    def list(self, parent_id: str | None = None, active_only: bool = False) -> list[SubagentRecord]:
        return [
            r for r in sorted(self._records.values(), key=lambda r: r.created_at)
            if (parent_id is None or r.parent_id == parent_id) and not (active_only and r.state.terminal)
        ]

    def pop_completed(self, parent_id: str) -> list[SubagentRecord]:
        """Finished, not-yet-reported children of ``parent_id`` (marks them delivered)."""
        out = [r for r in self._records.values() if r.parent_id == parent_id and r.state.terminal and not r.delivered]
        for r in out:
            r.delivered = True
        return out

    def completion_notes(self, parent_id: str) -> list[str]:
        """Human/model-readable notes for finished background children, for tool-result annotation."""
        notes = []
        for r in self.pop_completed(parent_id):
            body = r.summary or r.error or "(no output)"
            notes.append(f"[subagent {r.id} {r.state.value}] goal: {r.goal[:120]}\n{body[:1500]}")
        return notes

    # -- internals ------------------------------------------------------------

    @staticmethod
    def _log(rec: SubagentRecord, entry: dict[str, Any]) -> None:
        rec.log.append(entry)
        if len(rec.log) > _MAX_LOG:
            del rec.log[: len(rec.log) - _MAX_LOG]

    def _prune(self) -> None:
        cutoff = time.time() - TERMINAL_RETENTION_SECONDS
        for sid in [s for s, r in self._records.items() if r.state.terminal and (r.completed_at or 0) < cutoff]:
            for table in (self._records, self._done, self._tasks):
                table.pop(sid, None)

    async def _emit(self, method: str, params: dict[str, Any]) -> None:
        if self._on_event is None:
            return
        try:
            res = self._on_event(method, params)
            if asyncio.iscoroutine(res):
                await res
        except Exception:  # noqa: BLE001
            logger.debug("subagent event sink failed", exc_info=True)
