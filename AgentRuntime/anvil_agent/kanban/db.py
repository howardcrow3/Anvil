"""SQLite-backed Kanban board.

Design follows Hermes Agent's Kanban kernel (``hermes_cli/kanban_db*.py``; MIT, Nous Research — see
THIRD_PARTY_NOTICES.md), reduced to what Anvil needs: tasks with parent/child dependencies that
auto-promote, an atomic compare-and-swap claim so exactly one worker wins, one ``task_runs`` row per
attempt, an append-only event log, and a consecutive-failure circuit breaker that parks a flailing
task as ``blocked`` instead of retrying forever.

Statuses: ``todo`` (waiting on parents) -> ``ready`` -> ``running`` -> ``done``;
``blocked`` (needs a human or tripped the breaker); ``archived`` (hidden).
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

KANBAN_DIR = Path.home() / ".anvil" / "kanban"
STATUSES = ("todo", "ready", "running", "blocked", "done", "archived")
DEFAULT_FAILURE_LIMIT = 3
DEFAULT_CLAIM_TTL = 15 * 60

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY, title TEXT NOT NULL, body TEXT, assignee TEXT,
    status TEXT NOT NULL, priority INTEGER NOT NULL DEFAULT 0, created_by TEXT,
    created_at REAL NOT NULL, started_at REAL, completed_at REAL,
    project_dir TEXT, session_id TEXT, claim_lock TEXT, claim_expires REAL,
    result TEXT, idempotency_key TEXT UNIQUE, consecutive_failures INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS task_links (
    parent_id TEXT NOT NULL, child_id TEXT NOT NULL, PRIMARY KEY (parent_id, child_id)
);
CREATE TABLE IF NOT EXISTS task_comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, author TEXT NOT NULL,
    body TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS task_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, run_id INTEGER,
    kind TEXT NOT NULL, payload TEXT, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS task_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, claim_lock TEXT,
    subagent_id TEXT, started_at REAL NOT NULL, ended_at REAL, outcome TEXT, summary TEXT, error TEXT
);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_links_child ON task_links(child_id);
CREATE INDEX IF NOT EXISTS idx_events_task ON task_events(task_id, id);
CREATE INDEX IF NOT EXISTS idx_runs_task ON task_runs(task_id, id);
"""


class KanbanError(ValueError):
    pass


class KanbanDB:
    def __init__(
        self,
        path: Path | str | None = None,
        failure_limit: int = DEFAULT_FAILURE_LIMIT,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self.path = Path(path) if path else KANBAN_DIR / "default.db"
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.failure_limit = failure_limit
        self._on_event = on_event
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)

    # -- low level ------------------------------------------------------------

    def _tx(self):
        return _Tx(self)

    def _event(self, task_id: str, kind: str, payload: dict[str, Any] | None = None, run_id: int | None = None) -> None:
        self._conn.execute(
            "INSERT INTO task_events(task_id, run_id, kind, payload, created_at) VALUES (?,?,?,?,?)",
            (task_id, run_id, kind, json.dumps(payload or {}), time.time()),
        )
        if self._on_event:
            try:
                self._on_event("kanban.event", {"task_id": task_id, "kind": kind, **(payload or {})})
            except Exception:  # noqa: BLE001
                pass

    def _row(self, task_id: str) -> sqlite3.Row:
        row = self._conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            raise KanbanError(f"unknown task '{task_id}'")
        return row

    def _parents_open(self, task_id: str) -> bool:
        n = self._conn.execute(
            "SELECT COUNT(*) FROM task_links l JOIN tasks p ON p.id=l.parent_id "
            "WHERE l.child_id=? AND p.status NOT IN ('done','archived')",
            (task_id,),
        ).fetchone()[0]
        return n > 0

    def _promote_children(self, task_id: str) -> list[str]:
        promoted = []
        for r in self._conn.execute(
            "SELECT t.id FROM task_links l JOIN tasks t ON t.id=l.child_id WHERE l.parent_id=? AND t.status='todo'",
            (task_id,),
        ).fetchall():
            if not self._parents_open(r["id"]):
                self._conn.execute("UPDATE tasks SET status='ready' WHERE id=? AND status='todo'", (r["id"],))
                self._event(r["id"], "promoted", {"because": task_id})
                promoted.append(r["id"])
        return promoted

    def _close_run(self, task_id: str, outcome: str, summary: str | None = None, error: str | None = None) -> int | None:
        run = self._conn.execute(
            "SELECT id FROM task_runs WHERE task_id=? AND ended_at IS NULL ORDER BY id DESC LIMIT 1", (task_id,)
        ).fetchone()
        if run is None:
            return None
        self._conn.execute(
            "UPDATE task_runs SET ended_at=?, outcome=?, summary=?, error=? WHERE id=?",
            (time.time(), outcome, summary, error, run["id"]),
        )
        return run["id"]

    # -- create / link --------------------------------------------------------

    def create_task(
        self,
        title: str,
        body: str = "",
        *,
        assignee: str | None = None,
        priority: int = 0,
        parents: list[str] | None = None,
        created_by: str | None = None,
        project_dir: str | None = None,
        session_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        if not title.strip():
            raise KanbanError("title is required")
        with self._tx():
            if idempotency_key:
                hit = self._conn.execute("SELECT id FROM tasks WHERE idempotency_key=?", (idempotency_key,)).fetchone()
                if hit:
                    return self.get_task(hit["id"])
            for pid in parents or []:
                self._row(pid)
            tid = f"t_{uuid.uuid4().hex[:8]}"
            self._conn.execute(
                "INSERT INTO tasks(id,title,body,assignee,status,priority,created_by,created_at,project_dir,session_id,idempotency_key) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (tid, title.strip(), body, assignee, "todo", priority, created_by, time.time(), project_dir, session_id, idempotency_key),
            )
            for pid in parents or []:
                self._conn.execute("INSERT OR IGNORE INTO task_links VALUES (?,?)", (pid, tid))
            status = "todo" if self._parents_open(tid) else "ready"
            self._conn.execute("UPDATE tasks SET status=? WHERE id=?", (status, tid))
            self._event(tid, "created", {"status": status, "title": title.strip(), "by": created_by})
        return self.get_task(tid)

    def link(self, parent_id: str, child_id: str) -> None:
        if parent_id == child_id:
            raise KanbanError("a task cannot depend on itself")
        with self._tx():
            self._row(parent_id), self._row(child_id)
            if self._reaches(child_id, parent_id):
                raise KanbanError("link would create a dependency cycle")
            self._conn.execute("INSERT OR IGNORE INTO task_links VALUES (?,?)", (parent_id, child_id))
            if self._row(child_id)["status"] == "ready" and self._parents_open(child_id):
                self._conn.execute("UPDATE tasks SET status='todo' WHERE id=?", (child_id,))
            self._event(child_id, "linked", {"parent": parent_id})

    def _reaches(self, start: str, target: str) -> bool:
        seen, stack = set(), [start]
        while stack:
            cur = stack.pop()
            if cur == target:
                return True
            if cur in seen:
                continue
            seen.add(cur)
            stack += [r["child_id"] for r in self._conn.execute("SELECT child_id FROM task_links WHERE parent_id=?", (cur,))]
        return False

    # -- read -----------------------------------------------------------------

    def list_tasks(self, status: str | None = None, assignee: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        sql, args = "SELECT * FROM tasks WHERE status != 'archived'", []
        if status:
            sql, args = "SELECT * FROM tasks WHERE status=?", [status]
        if assignee:
            sql += " AND assignee=?"
            args.append(assignee)
        sql += " ORDER BY priority DESC, created_at ASC LIMIT ?"
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, (*args, limit))]

    def get_task(self, task_id: str) -> dict[str, Any]:
        with self._lock:
            t = dict(self._row(task_id))
            t["parents"] = [r["parent_id"] for r in self._conn.execute("SELECT parent_id FROM task_links WHERE child_id=?", (task_id,))]
            t["children"] = [r["child_id"] for r in self._conn.execute("SELECT child_id FROM task_links WHERE parent_id=?", (task_id,))]
            t["comments"] = [dict(r) for r in self._conn.execute("SELECT author, body, created_at FROM task_comments WHERE task_id=? ORDER BY id", (task_id,))]
            t["runs"] = [dict(r) for r in self._conn.execute("SELECT * FROM task_runs WHERE task_id=? ORDER BY id DESC LIMIT 5", (task_id,))]
            t["events"] = [dict(r) for r in self._conn.execute("SELECT kind, payload, created_at FROM task_events WHERE task_id=? ORDER BY id DESC LIMIT 20", (task_id,))]
            return t

    def parent_summaries(self, task_id: str) -> list[dict[str, str]]:
        with self._lock:
            return [
                {"id": r["id"], "title": r["title"], "result": r["result"] or ""}
                for r in self._conn.execute(
                    "SELECT p.id, p.title, p.result FROM task_links l JOIN tasks p ON p.id=l.parent_id WHERE l.child_id=?", (task_id,)
                )
            ]

    def ready_tasks(self, limit: int = 20) -> list[dict[str, Any]]:
        return self.list_tasks(status="ready", limit=limit)

    # -- state transitions ----------------------------------------------------

    def claim(self, task_id: str, ttl: float = DEFAULT_CLAIM_TTL, claimer: str | None = None) -> dict[str, Any] | None:
        """Atomically move ``ready`` -> ``running``. Exactly one caller wins; losers get ``None``."""
        lock = uuid.uuid4().hex
        with self._tx():
            cur = self._conn.execute(
                "UPDATE tasks SET status='running', claim_lock=?, claim_expires=?, started_at=COALESCE(started_at, ?) "
                "WHERE id=? AND status='ready'",
                (lock, time.time() + ttl, time.time(), task_id),
            )
            if cur.rowcount != 1:
                return None
            run = self._conn.execute(
                "INSERT INTO task_runs(task_id, claim_lock, started_at) VALUES (?,?,?)", (task_id, lock, time.time())
            )
            self._event(task_id, "claimed", {"by": claimer}, run.lastrowid)
        return self.get_task(task_id)

    def attach_subagent(self, task_id: str, subagent_id: str) -> None:
        with self._tx():
            self._conn.execute(
                "UPDATE task_runs SET subagent_id=? WHERE task_id=? AND ended_at IS NULL", (subagent_id, task_id)
            )

    def heartbeat(self, task_id: str, ttl: float = DEFAULT_CLAIM_TTL) -> bool:
        with self._tx():
            cur = self._conn.execute(
                "UPDATE tasks SET claim_expires=? WHERE id=? AND status='running'", (time.time() + ttl, task_id)
            )
            return cur.rowcount == 1

    def complete(self, task_id: str, summary: str = "", result: str | None = None, *, force: bool = False, by: str | None = None) -> dict[str, Any]:
        with self._tx():
            row = self._row(task_id)
            if row["status"] in ("done", "archived"):
                raise KanbanError(f"task is already {row['status']}")
            if row["status"] != "running" and not force:
                raise KanbanError(f"task is {row['status']}, not running")
            if self._parents_open(task_id) and not force:
                raise KanbanError("parents are not done")
            run_id = self._close_run(task_id, "completed", summary or None)
            self._conn.execute(
                "UPDATE tasks SET status='done', completed_at=?, result=?, claim_lock=NULL, claim_expires=NULL, consecutive_failures=0 WHERE id=?",
                (time.time(), result if result is not None else summary, task_id),
            )
            self._event(task_id, "completed", {"summary": summary[:500], "by": by}, run_id)
            promoted = self._promote_children(task_id)
        out = self.get_task(task_id)
        out["promoted"] = promoted
        return out

    def block(self, task_id: str, reason: str = "", *, by: str | None = None) -> dict[str, Any]:
        with self._tx():
            row = self._row(task_id)
            if row["status"] in ("done", "archived"):
                raise KanbanError(f"task is already {row['status']}")
            run_id = self._close_run(task_id, "blocked", error=reason or None)
            self._conn.execute(
                "UPDATE tasks SET status='blocked', claim_lock=NULL, claim_expires=NULL WHERE id=?", (task_id,)
            )
            self._event(task_id, "blocked", {"reason": reason[:500], "by": by}, run_id)
        return self.get_task(task_id)

    def unblock(self, task_id: str) -> dict[str, Any]:
        with self._tx():
            row = self._row(task_id)
            if row["status"] != "blocked":
                raise KanbanError(f"task is {row['status']}, not blocked")
            status = "todo" if self._parents_open(task_id) else "ready"
            self._conn.execute("UPDATE tasks SET status=?, consecutive_failures=0 WHERE id=?", (status, task_id))
            self._event(task_id, "unblocked", {"status": status})
        return self.get_task(task_id)

    def fail(self, task_id: str, error: str, outcome: str = "crashed") -> dict[str, Any]:
        """Record a failed attempt. Past ``failure_limit`` consecutive failures the task is parked as blocked."""
        with self._tx():
            row = self._row(task_id)
            if row["status"] != "running":
                return self.get_task(task_id)
            failures = row["consecutive_failures"] + 1
            run_id = self._close_run(task_id, outcome, error=error[:1000])
            if failures >= self.failure_limit:
                status, kind = "blocked", "gave_up"
            else:
                status, kind = "ready", "retry"
            self._conn.execute(
                "UPDATE tasks SET status=?, consecutive_failures=?, claim_lock=NULL, claim_expires=NULL WHERE id=?",
                (status, failures, task_id),
            )
            self._event(task_id, kind, {"error": error[:500], "failures": failures, "outcome": outcome}, run_id)
        return self.get_task(task_id)

    def reclaim_expired(self, now: float | None = None) -> list[str]:
        now = now or time.time()
        with self._lock:
            ids = [r["id"] for r in self._conn.execute("SELECT id FROM tasks WHERE status='running' AND claim_expires < ?", (now,))]
        for tid in ids:
            self.fail(tid, "claim expired (worker stopped responding)", outcome="reclaimed")
        return ids

    def comment(self, task_id: str, author: str, body: str) -> None:
        if not body.strip():
            raise KanbanError("comment body is required")
        with self._tx():
            self._row(task_id)
            self._conn.execute(
                "INSERT INTO task_comments(task_id, author, body, created_at) VALUES (?,?,?,?)", (task_id, author, body.strip(), time.time())
            )
            self._event(task_id, "comment", {"author": author})

    def archive(self, task_id: str) -> None:
        with self._tx():
            self._row(task_id)
            self._close_run(task_id, "archived")
            self._conn.execute("UPDATE tasks SET status='archived', claim_lock=NULL, claim_expires=NULL WHERE id=?", (task_id,))
            self._event(task_id, "archived")
            self._promote_children(task_id)

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {r["status"]: r["n"] for r in self._conn.execute("SELECT status, COUNT(*) n FROM tasks GROUP BY status")}

    def close(self) -> None:
        self._conn.close()


class _Tx:
    """BEGIN IMMEDIATE ... COMMIT under the DB lock (SQLite serializes writers, so claims can't race)."""

    def __init__(self, db: KanbanDB) -> None:
        self._db = db
        self._outer = False

    def __enter__(self):
        self._db._lock.acquire()
        self._outer = not self._db._conn.in_transaction
        if self._outer:
            self._db._conn.execute("BEGIN IMMEDIATE")
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if self._outer:
                self._db._conn.execute("ROLLBACK" if exc_type else "COMMIT")
        finally:
            self._db._lock.release()
        return False
