import pytest

from anvil_agent.compaction import SUMMARY_MARKER, Compactor, estimate_tokens
from anvil_agent.models.types import ChatMessage, ToolCallRequest


def _round(i, size=3000, name="read_file", args=None):
    cid = f"c{i}"
    return [
        ChatMessage(role="assistant", content="", tool_calls=[ToolCallRequest(id=cid, name=name, arguments=args or {"path": f"f{i}"})]),
        ChatMessage(role="tool", content=f"{i}" * size, tool_call_id=cid),
    ]


def _convo(rounds):
    msgs = [ChatMessage(role="system", content="sys"), ChatMessage(role="user", content="fix the bug")]
    for i in range(rounds):
        msgs += _round(i)
    msgs.append(ChatMessage(role="assistant", content="working"))
    return msgs


def _valid(msgs):
    """No orphan tool results; no two same-role rows in a row (except consecutive tool rows)."""
    ids = set()
    for m in msgs:
        if m.role == "assistant":
            ids = {tc.id for tc in m.tool_calls}
        if m.role == "tool":
            assert m.tool_call_id in ids
    for a, b in zip(msgs, msgs[1:]):
        if a.role == b.role:
            assert a.role == "tool"


def test_prune_stubs_old_results_only():
    c = Compactor(context_window=10_000)
    msgs = _convo(20)
    out, n = c.prune(msgs)
    assert n > 0
    assert "output pruned" in out[3].content
    assert out[-2].content == msgs[-2].content  # protected tail intact
    assert estimate_tokens(out) < estimate_tokens(msgs)


def test_dedup_identical_results():
    c = Compactor(context_window=10**9, protect_last_n=2)
    msgs = [ChatMessage(role="system", content="s"), ChatMessage(role="user", content="u")]
    for i in range(6):
        cid = f"c{i}"
        msgs += [
            ChatMessage(role="assistant", content="", tool_calls=[ToolCallRequest(id=cid, name="read_file", arguments={"path": "a"})]),
            ChatMessage(role="tool", content="same" * 300, tool_call_id=cid),
        ]
    out, n = c.prune(msgs)
    assert n >= 4 and out[-1].content == "same" * 300


@pytest.mark.asyncio
async def test_summary_replaces_middle_and_keeps_validity():
    c = Compactor(context_window=4_000, threshold=0.25)
    msgs = _convo(30)

    async def summarize(prompt):
        assert "TRANSCRIPT" in prompt
        return "## Goal\nfix the bug"

    res = await c.compact(msgs, summarize)
    assert res.summarized and not res.used_fallback
    assert len(res.messages) < len(msgs)
    assert res.messages[0].role == "system"
    assert any(SUMMARY_MARKER in m.content for m in res.messages)
    assert res.tokens_after < res.tokens_before
    _valid(res.messages)


@pytest.mark.asyncio
async def test_summary_failure_falls_back_without_raising():
    c = Compactor(context_window=4_000, threshold=0.25)

    async def boom(prompt):
        raise RuntimeError("model down")

    res = await c.compact(_convo(30), boom)
    assert res.summarized and res.used_fallback
    _valid(res.messages)


@pytest.mark.asyncio
async def test_below_threshold_is_noop():
    c = Compactor(context_window=1_000_000)
    msgs = _convo(3)
    res = await c.compact(msgs, None)
    assert not res.changed and res.messages == msgs
