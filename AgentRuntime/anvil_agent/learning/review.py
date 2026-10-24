"""Background review: after enough turns/tool use, a restricted subagent reads the conversation and saves
durable memory and reusable skills. Prompts and trigger policy adapted from Hermes Agent's background
review (MIT, Nous Research — see THIRD_PARTY_NOTICES.md).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from anvil_agent.models.types import ChatMessage
from anvil_agent.subagents.manager import SubagentManager, SubagentSpec, SubagentState

logger = logging.getLogger(__name__)

REVIEW_TOOLS = ["memory", "skills_list", "skill_view", "skill_manage"]

MEMORY_PROMPT = """\
Review the conversation above and decide whether anything is worth saving to memory.
Focus on: (1) the user's persona, preferences, communication style and corrections they made;
(2) durable facts about their environment, projects and conventions.
Use the `memory` tool (target='user' or 'memory'). Do NOT save task progress, one-off results, or secrets.
If nothing qualifies, reply exactly: Nothing to save."""

SKILL_PROMPT = """\
Review the conversation above and decide whether a reusable skill should be created or improved.
Save a skill when a non-trivial approach was discovered through trial and error, a user corrected the
method, or a multi-step workflow is likely to recur. First call skills_list; if an existing skill covers
it, skill_view then skill_manage(action='patch') it rather than creating a near-duplicate. New skills need
SKILL.md frontmatter (name, description) and sections: When to Use, Procedure, Pitfalls, Verification.
If nothing qualifies, reply exactly: Nothing to save."""

COMBINED_PROMPT = MEMORY_PROMPT + "\n\nThen, separately:\n" + SKILL_PROMPT


@dataclass
class ReviewConfig:
    enabled: bool = True
    memory_every_turns: int = 10
    skill_min_tool_calls: int = 8
    min_messages: int = 4
    max_transcript_chars: int = 40_000


class ReviewManager:
    def __init__(
        self,
        subagents: SubagentManager,
        config: ReviewConfig | None = None,
        on_result: Callable[[dict[str, Any]], Awaitable[None] | None] | None = None,
    ) -> None:
        self._agents = subagents
        self.cfg = config or ReviewConfig()
        self._on_result = on_result
        self._turns = 0
        self._tools = 0
        self._current: str | None = None

    # -- trigger policy -------------------------------------------------------------

    def note_turn(self, tool_calls: int) -> tuple[bool, bool]:
        """Record a finished user turn. Returns (review_memory, review_skills) and resets counters that fired."""
        self._turns += 1
        self._tools += tool_calls
        mem = self._turns >= self.cfg.memory_every_turns
        skill = self._tools >= self.cfg.skill_min_tool_calls
        if mem:
            self._turns = 0
        if skill:
            self._tools = 0
        return mem, skill

    async def stop_running(self) -> None:
        """Stop an in-flight review (call when a live turn starts; matters for single-slot local models)."""
        if self._current:
            await self._agents.stop(self._current)
            self._current = None

    # -- running ----------------------------------------------------------------------

    @staticmethod
    def render_transcript(messages: list[ChatMessage], limit: int) -> str:
        lines: list[str] = []
        for m in messages:
            if m.role == "system":
                continue
            text = (m.content or "").strip()
            if m.role == "tool":
                text = text[:300] + (" …" if len(text) > 300 else "")
            if m.tool_calls:
                text += " [calls: " + ", ".join(tc.name for tc in m.tool_calls) + "]"
            if text:
                lines.append(f"{m.role.upper()}: {text}")
        out = "\n".join(lines)
        return out[-limit:]

    async def maybe_review(self, messages: list[ChatMessage], tool_calls: int, model: str | None = None) -> str | None:
        """Fire-and-forget entry point after a turn. Returns the subagent id if a review was started."""
        if not self.cfg.enabled or len([m for m in messages if m.role != "system"]) < self.cfg.min_messages:
            return None
        mem, skill = self.note_turn(tool_calls)
        if not (mem or skill):
            return None
        return await self.start(messages, memory=mem, skills=skill, model=model)

    async def start(self, messages: list[ChatMessage], memory: bool, skills: bool, model: str | None = None) -> str | None:
        if self._current:
            return None
        prompt = COMBINED_PROMPT if memory and skills else MEMORY_PROMPT if memory else SKILL_PROMPT
        transcript = self.render_transcript(messages, self.cfg.max_transcript_chars)
        spec = SubagentSpec(
            goal=prompt, context=f"<conversation>\n{transcript}\n</conversation>", role="reviewer", model=model,
            allowed_tools=REVIEW_TOOLS, max_iterations=12, timeout_seconds=300, env={"unattended": True, "review": True},
        )
        rec = await self._agents.spawn(spec, parent_id=None)
        self._current = rec.id
        import asyncio
        asyncio.create_task(self._finish(rec.id, memory, skills))
        return rec.id

    async def _finish(self, sid: str, memory: bool, skills: bool) -> None:
        try:
            rec = await self._agents.wait(sid)
            summary = (rec.summary or "").strip()
            saved = rec.state is SubagentState.SUCCEEDED and summary and not summary.lower().startswith("nothing to save")
            payload = {"id": sid, "memory": memory, "skills": skills, "state": rec.state.value, "saved": bool(saved),
                       "summary": summary if saved else "", "error": rec.error}
            if self._on_result:
                r = self._on_result(payload)
                if hasattr(r, "__await__"):
                    await r
        except Exception:  # noqa: BLE001
            logger.exception("review finish failed")
        finally:
            if self._current == sid:
                self._current = None
