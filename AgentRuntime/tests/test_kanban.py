import asyncio
import pytest

from anvil_agent.kanban.db import KanbanDB, KanbanError


@pytest.fixture
def db():
    d = KanbanDB(":memory:", failure_limit=2)
    yield d
    d.close()


def test_create_and_dependency_promotion(db):
    a = db.create_task("A")
    b = db.create_task("B", parents=[a["id"]])
    assert a["status"] == "ready" and b["status"] == "todo"
    db.claim(a["id"])
    out = db.complete(a["id"], "done A")
    assert b["id"] in out["promoted"]
    assert db.get_task(b["id"])["status"] == "ready"
    assert db.parent_summaries(b["id"])[0]["result"] == "done A"


def test_claim_is_exclusive(db):
    a = db.create_task("A")
    assert db.claim(a["id"]) is not None
    assert db.claim(a["id"]) is None


def test_cycle_rejected(db):
    a, b = db.create_task("A"), db.create_task("B")
    db.link(a["id"], b["id"])
    with pytest.raises(KanbanError):
        db.link(b["id"], a["id"])


def test_circuit_breaker(db):
    a = db.create_task("A")
    db.claim(a["id"]); db.fail(a["id"], "boom")
    assert db.get_task(a["id"])["status"] == "ready"
    db.claim(a["id"]); db.fail(a["id"], "boom")
    assert db.get_task(a["id"])["status"] == "blocked"
    assert db.unblock(a["id"])["status"] == "ready"


def test_reclaim_expired(db):
    a = db.create_task("A")
    db.claim(a["id"], ttl=-1)
    assert db.reclaim_expired() == [a["id"]]
    assert db.get_task(a["id"])["status"] == "ready"


def test_idempotency_and_complete_guard(db):
    a = db.create_task("A", idempotency_key="k")
    assert db.create_task("A2", idempotency_key="k")["id"] == a["id"]
    with pytest.raises(KanbanError):
        db.complete(a["id"], "x")  # not running


@pytest.mark.asyncio
async def test_dispatcher_runs_worker_and_auto_completes():
    from anvil_agent.kanban.dispatcher import KanbanDispatcher
    from anvil_agent.subagents.manager import SubagentState

    class Rec:
        id = "sa1"; state = SubagentState.SUCCEEDED; summary = "all good"; error = None

    class FakeAgents:
        async def spawn(self, spec, parent_id=None):
            assert spec.env["kanban_task"]
            return Rec()
        async def wait(self, sid):
            return Rec()

    db = KanbanDB(":memory:")
    t = db.create_task("T")
    disp = KanbanDispatcher(db, FakeAgents(), poll_seconds=0.01)
    assert await disp.tick() == [t["id"]]
    await asyncio.gather(*disp._watchers.values())
    got = db.get_task(t["id"])
    assert got["status"] == "done" and got["result"] == "all good"
