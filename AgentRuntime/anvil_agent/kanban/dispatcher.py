"""Kanban dispatcher: claims ready tasks and runs each as a subagent worker.

Mirrors the role of Hermes Agent's kanban dispatcher (MIT, Nous Research — see THIRD_PARTY_NOTICES.md):
reclaim stale claims, claim up to ``max_workers`` ready tasks by priority, run a worker per task with
the parents' results as context, heartbeat the claim while it runs, then reconcile the outcome.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from anvil_agent.kanban.db import DEFAULT_CLAIM_TTL, KanbanDB, KanbanError
from anvil_agent.subagents.manager import SubagentManager, SubagentSpec, SubagentState

logger = logging.getLogger(__name__)

WORKER_INSTRUCTIONS = """\
You are an autonomous worker on kanban task {task_id}. Nobody is watching; do not ask questions.
Do the work described below, then finish by calling the `kanban` tool (if it is hidden, find it with
tool_search and run it with tool_call):
  - action="complete", summary="<what you did and the result>" when done
  - action="block", reason="<what you need>" if you cannot proceed without a human
  - action="comment", body="..." to leave progress notes
Keep the summary self-contained: dependent tasks will read it as their input.
"""


class KanbanDispatcher:
    def __init__(
        self,
        db: KanbanDB,
        subagents: SubagentManager,
        project_dir: str = "",
        max_workers: int = 2,
        poll_seconds: float = 5.0,
        claim_ttl: float = DEFAULT_CLAIM_TTL,
        task_timeout: float = 1800.0,
    ) -> None:
        self._db = db
        self._agents = subagents
        self._project_dir = project_dir
        self.max_workers = max_workers
        self._poll = poll_seconds
        self._ttl = claim_ttl
        self._timeout = task_timeout
        self._watchers: dict[str, asyncio.Task[None]] = {}
        self._runner: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        return self._runner is not None and not self._runner.done()

    @property
    def active_tasks(self) -> list[str]:
        return [t for t, w in self._watchers.items() if not w.done()]

    async def start(self) -> None:
        if not self.running:
            self._runner = asyncio.create_task(self._loop())

    async def stop(self, stop_workers: bool = True) -> None:
        if self._runner:
            self._runner.cancel()
            try:
                await self._runner
            except asyncio.CancelledError:
                pass
            self._runner = None
        if stop_workers:
            for task_id in list(self.active_tasks):
                await self.stop_task(task_id)

    async def stop_task(self, task_id: str) -> bool:
        """Stop a running worker and park its task as blocked."""
        rec_id = next((r.get("subagent_id") for r in self._db.get_task(task_id)["runs"] if r.get("ended_at") is None), None)
        if rec_id:
            await self._agents.stop(rec_id)
        return bool(rec_id)

    async def _loop(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:  # noqa: BLE001 - the dispatcher must survive a bad tick
                logger.exception("kanban dispatcher tick failed")
            await asyncio.sleep(self._poll)

    async def tick(self) -> list[str]:
        self._db.reclaim_expired()
        self._watchers = {t: w for t, w in self._watchers.items() if not w.done()}
        slots = self.max_workers - len(self._watchers)
        dispatched: list[str] = []
        if slots <= 0:
            return dispatched
        for task in self._db.ready_tasks(limit=slots * 3):
            if len(dispatched) >= slots:
                break
            claimed = self._db.claim(task["id"], ttl=self._ttl, claimer="dispatcher")
            if claimed is None:
                continue
            await self._launch(claimed)
            dispatched.append(task["id"])
        return dispatched

    async def _launch(self, task: dict[str, Any]) -> None:
        tid = task["id"]
        parents = self._db.parent_summaries(tid)
        context_parts = [f"Task title: {task['title']}", task.get("body") or ""]
        if parents:
            context_parts.append("Results from the tasks this one depends on:")
            context_parts += [f"- {p['id']} {p['title']}: {p['result'][:1500]}" for p in parents]
        if task.get("project_dir") or self._project_dir:
            context_parts.append(f"Project directory: {task.get('project_dir') or self._project_dir}")
        spec = SubagentSpec(
            goal=WORKER_INSTRUCTIONS.format(task_id=tid) + f"\nTask {tid}: {task['title']}",
            context="\n".join(p for p in context_parts if p),
            role=task.get("assignee") or "worker",
            max_iterations=60,
            timeout_seconds=self._timeout,
            env={"kanban_task": tid, "unattended": True},
        )
        try:
            rec = await self._agents.spawn(spec, parent_id=None)
        except Exception as exc:  # noqa: BLE001
            self._db.fail(tid, f"spawn failed: {exc}", outcome="spawn_failed")
            return
        self._db.attach_subagent(tid, rec.id)
        self._watchers[tid] = asyncio.create_task(self._watch(tid, rec.id))

    async def _watch(self, task_id: str, subagent_id: str) -> None:
        waiter = asyncio.create_task(self._agents.wait(subagent_id))
        try:
            while not waiter.done():
                await asyncio.wait({waiter}, timeout=max(1.0, self._ttl / 3))
                if not waiter.done():
                    self._db.heartbeat(task_id, self._ttl)
            rec = waiter.result()
            self._reconcile(task_id, rec)
        except asyncio.CancelledError:
            waiter.cancel()
            raise
        except Exception:  # noqa: BLE001
            logger.exception("kanban watcher failed for %s", task_id)

    def _reconcile(self, task_id: str, rec: Any) -> None:
        task = self._db.get_task(task_id)
        if task["status"] != "running":  # the worker already completed/blocked via the kanban tool
            return
        if rec.state is SubagentState.SUCCEEDED:
            summary = rec.summary or "(worker finished without a summary)"
            self._db._event(task_id, "auto_completed", {"subagent": rec.id})
            try:
                self._db.complete(task_id, summary, by=f"auto:{rec.id}")
            except KanbanError:
                logger.debug("auto-complete refused for %s", task_id, exc_info=True)
        elif rec.state is SubagentState.CANCELLED:
            self._db.block(task_id, "stopped by user", by="user")
        else:
            self._db.fail(task_id, rec.error or "worker failed", outcome="crashed")
