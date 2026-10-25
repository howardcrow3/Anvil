import asyncio
import json
import time
import pytest

from anvil_agent.learning.curator import Curator, DAY
from anvil_agent.learning.review import ReviewManager, ReviewConfig
from anvil_agent.models.types import ChatMessage
from anvil_agent.subagents.manager import SubagentState
from anvil_agent.tools.skill_tools import MemoryTool, SkillTools

SKILL = "---\nname: demo\ndescription: a demo\n---\n# Demo\n\n## Procedure\n1. step\n"


async def call(tool, **kw):
    r = await tool.execute(kw)
    return r.is_error, r.content


@pytest.mark.asyncio
async def test_skill_create_patch_guards(tmp_path):
    st = SkillTools(tmp_path)
    lst, view, manage = st.tools()
    assert not (await call(manage, action="create", name="demo", content=SKILL))[0]
    assert (await call(manage, action="create", name="demo", content=SKILL))[0]  # duplicate
    assert (await call(manage, action="create", name="../evil", content=SKILL))[0]
    assert (await call(manage, action="create", name="bad", content="no frontmatter"))[0]
    assert "created_by: agent" in (tmp_path / "demo" / "SKILL.md").read_text()
    st.read.clear()
    assert (await call(manage, action="patch", name="demo", old_string="1. step", new_string="1. better"))[0]  # unread
    await call(view, name="demo")
    assert not (await call(manage, action="patch", name="demo", old_string="1. step", new_string="1. better"))[0]
    assert (await call(manage, action="write_file", name="demo", file_path="../x.txt", content="x"))[0]
    assert not (await call(manage, action="write_file", name="demo", file_path="references/a.md", content="x"))[0]
    err, out = await call(lst)
    assert json.loads(out)["skills"][0]["agent_created"] is True


@pytest.mark.asyncio
async def test_memory_tool_limits_and_redaction(tmp_path):
    m = MemoryTool(tmp_path)
    assert not (await call(m, action="add", target="user", content="likes terse answers"))[0]
    assert not (await call(m, action="replace", target="user", old_text="terse", content="likes very terse answers"))[0]
    assert (await call(m, action="remove", target="user", old_text="nomatch"))[0]
    assert (await call(m, action="add", target="memory", content="x" * 9000))[0]
    await call(m, action="add", target="memory", content="key sk-ant-api03-" + "a" * 40)
    assert "sk-ant-api03-" + "a" * 40 not in (tmp_path / "MEMORY.md").read_text()


def test_curator_transitions_and_pin(tmp_path):
    st = SkillTools(tmp_path)
    for n in ("old", "mid", "pinned", "user"):
        (tmp_path / n).mkdir()
        (tmp_path / n / "SKILL.md").write_text(SKILL)
    now = time.time()
    c = Curator(tmp_path, stale_after_days=30, archive_after_days=90)
    for n, age in (("old", 100), ("mid", 40), ("pinned", 200)):
        c.usage.update(n, created_by="agent", created_at=now - age * DAY, last_used_at=now - age * DAY)
    c.pin("pinned")
    (tmp_path / "user" / "SKILL.md").write_text(SKILL.replace("a demo", "mine"))  # no created_by -> user's
    res = c.apply_automatic_transitions(now)
    assert res["archived"] == ["old"] and res["marked_stale"] == ["mid"]
    assert (tmp_path / ".archive" / "old" / "SKILL.md").exists() and (tmp_path / "pinned").exists() and (tmp_path / "user").exists()
    assert c.restore("old") and (tmp_path / "old").exists()


def test_curator_should_run(tmp_path):
    c = Curator(tmp_path, interval_hours=1, min_idle_hours=1)
    now = time.time()
    assert c.should_run(now, last_activity=now - 7200)
    assert not c.should_run(now, last_activity=now - 10)
    asyncio.run(c.run(now=now))
    assert not c.should_run(now + 60, last_activity=now - 7200)


@pytest.mark.asyncio
async def test_review_trigger_and_result():
    class Rec:
        id = "r1"; state = SubagentState.SUCCEEDED; summary = "Saved 1 memory"; error = None

    class Agents:
        specs = []
        async def spawn(self, spec, parent_id=None):
            self.specs.append(spec); return Rec()
        async def wait(self, sid): return Rec()

    got = []
    rm = ReviewManager(Agents(), ReviewConfig(memory_every_turns=2, skill_min_tool_calls=100, min_messages=2), on_result=got.append)
    msgs = [ChatMessage(role="user", content="hi"), ChatMessage(role="assistant", content="yo")]
    assert await rm.maybe_review(msgs, 1) is None
    assert await rm.maybe_review(msgs, 1) == "r1"
    await asyncio.sleep(0.05)
    assert got and got[0]["saved"] and rm._current is None
    spec = Agents.specs[0]
    assert spec.allowed_tools == ["memory", "skills_list", "skill_view", "skill_manage"]
