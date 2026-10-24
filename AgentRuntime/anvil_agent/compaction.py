"""Context compaction for long agent runs.

Adapted from the ideas in Hermes Agent's ``agent/context_compressor*.py`` (MIT, Nous Research; see
THIRD_PARTY_NOTICES.md). Two layers, cheapest first:

1. Deterministic prune (no model call): back-reference byte-identical tool results, replace large
   *old* tool results with one-line stubs, and shorten huge tool-call arguments on old turns.
2. Summary: if still over budget, replace the middle of the transcript with a model-written summary,
   keeping the system prompt, the first user request, and a recent tail intact.

Compaction is the one sanctioned mutation of past context. The tail never splits an
assistant-tool_calls / tool-result group, and message roles keep strict alternation.
If the summary model fails, a deterministic summary is inserted instead of aborting.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from dataclasses import dataclass
from typing import Awaitable, Callable

from anvil_agent.models.types import ChatMessage

logger = logging.getLogger(__name__)

SUMMARY_MARKER = "[Earlier conversation compacted]"
_STUB_MARK = "output pruned"
_DUP_MARK = "duplicate of a later"

SUMMARY_PROMPT = """You are compacting an AI coding agent's transcript so work can continue.
Write a faithful, compact summary of the conversation below using exactly these sections:

## Goal
## Progress so far
## Files and commands touched
## Decisions and constraints
## Open items / next steps

Keep concrete details the agent will need (paths, function names, error messages, user preferences).
Do not invent anything. Do not address the user.

--- TRANSCRIPT ---
{transcript}
"""

Summarizer = Callable[[str], Awaitable[str]]


def estimate_tokens(messages: list[ChatMessage]) -> int:
    """Cheap token estimate (~4 chars/token) including tool-call arguments."""
    chars = 0
    for m in messages:
        chars += len(m.content) + 16
        for tc in m.tool_calls:
            chars += len(tc.name) + len(json.dumps(tc.arguments, default=str))
    return chars // 4


@dataclass
class CompactionResult:
    messages: list[ChatMessage]
    pruned: int = 0
    summarized: bool = False
    used_fallback: bool = False
    tokens_before: int = 0
    tokens_after: int = 0

    @property
    def changed(self) -> bool:
        return self.pruned > 0 or self.summarized


class Compactor:
    def __init__(
        self,
        context_window: int,
        threshold: float = 0.5,
        protect_last_n: int = 10,
        min_prune_chars: int = 1500,
        summary_cooldown: int = 3,
    ) -> None:
        self.context_window = context_window
        self.threshold_tokens = int(context_window * threshold)
        self.protect_last_n = protect_last_n
        self.min_prune_chars = min_prune_chars
        self._summary_cooldown = summary_cooldown
        self._cooldown_left = 0

    # -- public ---------------------------------------------------------------

    def needs_compaction(self, messages: list[ChatMessage]) -> bool:
        return estimate_tokens(messages) >= self.threshold_tokens

    async def compact(self, messages: list[ChatMessage], summarize: Summarizer | None) -> CompactionResult:
        before = estimate_tokens(messages)
        pruned_msgs, pruned = self.prune(messages)
        result = CompactionResult(pruned_msgs, pruned=pruned, tokens_before=before)
        if estimate_tokens(pruned_msgs) < self.threshold_tokens:
            result.tokens_after = estimate_tokens(pruned_msgs)
            return result

        bounds = self._boundaries(pruned_msgs)
        if bounds is None:
            result.tokens_after = estimate_tokens(pruned_msgs)
            return result
        head_end, tail_start = bounds
        middle = pruned_msgs[head_end:tail_start]

        summary: str | None = None
        if summarize is not None and self._cooldown_left <= 0:
            try:
                summary = (await summarize(SUMMARY_PROMPT.format(transcript=_render(middle)))).strip()
            except Exception:  # noqa: BLE001 - never abort the run because the summarizer failed
                logger.warning("Compaction summary failed; using deterministic summary", exc_info=True)
                self._cooldown_left = self._summary_cooldown
        elif self._cooldown_left > 0:
            self._cooldown_left -= 1
        if not summary:
            summary = _fallback_summary(middle)
            result.used_fallback = True

        result.messages = self._splice(pruned_msgs, head_end, tail_start, summary)
        result.summarized = True
        result.tokens_after = estimate_tokens(result.messages)
        return result

    def prune(self, messages: list[ChatMessage]) -> tuple[list[ChatMessage], int]:
        """Deterministic, no-model prune. Returns (new list, number of messages rewritten)."""
        if len(messages) <= self.protect_last_n + 2:
            return messages, 0
        names = _call_index(messages)
        tail_start = self._align_tail(messages, len(messages) - self.protect_last_n)
        out = list(messages)
        changed = 0

        # (1) Dedup byte-identical tool results anywhere; the newest copy stays whole.
        seen: dict[str, int] = {}
        for i in range(len(out) - 1, -1, -1):
            m = out[i]
            if m.role != "tool" or len(m.content) < 512:
                continue
            if m.content in seen:
                name = names.get(m.tool_call_id or "", ("tool", ""))[0]
                out[i] = m.model_copy(update={
                    "content": f"[{name} result: {_DUP_MARK} identical result, {len(m.content):,} chars omitted]"
                })
                changed += 1
            else:
                seen[m.content] = i

        # (2) Replace large old tool results with a stub + short preview.
        for i in range(1, tail_start):
            m = out[i]
            if m.role != "tool" or len(m.content) < self.min_prune_chars:
                continue
            if _STUB_MARK in m.content[:200] or _DUP_MARK in m.content[:200]:
                continue
            name, argp = names.get(m.tool_call_id or "", ("tool", ""))
            preview = m.content[:200].replace("\n", " ")
            out[i] = m.model_copy(update={
                "content": f"[{name}({argp}) {_STUB_MARK} — {len(m.content):,} chars. Re-run the tool if needed.] {preview}…"
            })
            changed += 1

        # (3) Shorten huge string arguments (e.g. write_file content) on old assistant turns.
        for i in range(1, tail_start):
            m = out[i]
            if m.role != "assistant" or not m.tool_calls:
                continue
            new_calls, touched = [], False
            for tc in m.tool_calls:
                args = {
                    k: (f"[{len(v):,} chars omitted]" if isinstance(v, str) and len(v) > 2000 else v)
                    for k, v in tc.arguments.items()
                }
                if args != tc.arguments:
                    touched = True
                new_calls.append(tc.model_copy(update={"arguments": args}))
            if touched:
                out[i] = m.model_copy(update={"tool_calls": new_calls})
                changed += 1
        return (out if changed else messages), changed

    # -- internals ------------------------------------------------------------

    def _align_tail(self, messages: list[ChatMessage], start: int) -> int:
        """Never start the protected tail on a tool result: move back to the assistant that issued it."""
        start = max(1, min(start, len(messages)))
        while start > 1 and start < len(messages) and messages[start].role == "tool":
            start -= 1
        return start

    def _boundaries(self, messages: list[ChatMessage]) -> tuple[int, int] | None:
        first_user = next((i for i, m in enumerate(messages) if m.role == "user"), None)
        head_end = (first_user + 1) if first_user is not None else 1
        tail_start = self._align_tail(messages, len(messages) - self.protect_last_n)
        if tail_start - head_end < 4:
            return None
        return head_end, tail_start

    def _splice(
        self, messages: list[ChatMessage], head_end: int, tail_start: int, summary: str
    ) -> list[ChatMessage]:
        head, tail = list(messages[:head_end]), list(messages[tail_start:])
        block = f"{SUMMARY_MARKER}\n{summary}"
        if tail and tail[0].role == "user":
            # user, [assistant summary], user — keeps alternation.
            return head + [ChatMessage(role="assistant", content=block)] + tail
        if head and head[-1].role == "user":
            merged = head[-1].model_copy(update={"content": f"{head[-1].content}\n\n{block}"})
            return head[:-1] + [merged] + tail
        return head + [ChatMessage(role="user", content=block)] + tail


def _call_index(messages: list[ChatMessage]) -> dict[str, tuple[str, str]]:
    idx: dict[str, tuple[str, str]] = {}
    for m in messages:
        for tc in m.tool_calls:
            idx[tc.id] = (tc.name, _args_preview(tc.arguments))
    return idx


def _args_preview(args: dict, limit: int = 80) -> str:
    text = json.dumps(args, default=str, separators=(",", ":"))
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _render(middle: list[ChatMessage], per_msg: int = 1500, total: int = 24000) -> str:
    lines: list[str] = []
    for m in middle:
        if m.role == "assistant" and m.tool_calls:
            calls = "; ".join(f"{tc.name}({_args_preview(tc.arguments, 120)})" for tc in m.tool_calls)
            body = (m.content[:per_msg] + " " if m.content else "") + f"[calls: {calls}]"
        else:
            body = m.content[:per_msg] + ("…" if len(m.content) > per_msg else "")
        lines.append(f"{m.role.upper()}: {body}")
    text = "\n".join(lines)
    return text if len(text) <= total else text[: total // 2] + "\n…[middle omitted]…\n" + text[-total // 2 :]


def _fallback_summary(middle: list[ChatMessage]) -> str:
    users = [m.content.strip().replace("\n", " ")[:200] for m in middle if m.role == "user" and m.content.strip()]
    tools = Counter(tc.name for m in middle for tc in m.tool_calls)
    paths = sorted({
        str(v) for m in middle for tc in m.tool_calls for k, v in tc.arguments.items()
        if k in ("path", "file_path") and isinstance(v, str)
    })[:20]
    parts = [f"{len(middle)} earlier messages were compacted without a model-written summary."]
    if users:
        parts.append("User requests in that span: " + " | ".join(users[-5:]))
    if tools:
        parts.append("Tools used: " + ", ".join(f"{n}×{c}" for n, c in tools.most_common()))
    if paths:
        parts.append("Files touched: " + ", ".join(paths))
    return "\n".join(parts)
