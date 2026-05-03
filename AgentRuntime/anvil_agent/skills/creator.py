"""Autonomous skill creation from successful tool-use patterns."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

USER_SKILLS_DIR = Path.home() / ".anvil" / "skills"

SKILL_TEMPLATE = """\
---
name: {name}
description: {description}
version: 1.0.0
created_by: anvil-auto
---
# {title}

## When to Use
{when_to_use}

## Procedure
{procedure}

## Pitfalls
{pitfalls}

## Verification
{verification}
"""


class SkillCreator:
    """Detects when a conversation pattern should become a reusable skill."""

    def __init__(self, skills_dir: Path = USER_SKILLS_DIR) -> None:
        self._skills_dir = skills_dir

    def should_create_skill(self, tool_call_count: int, success: bool) -> bool:
        """Return True if the conversation warrants skill extraction."""
        return tool_call_count >= 5 and success

    async def create_skill(
        self, conversation_summary: str, tool_calls: list[dict[str, Any]]
    ) -> str | None:
        """Generate SKILL.md content from conversation data.

        This is a template for future LLM-based generation.
        Currently creates a skeleton from tool call data.
        """
        if not tool_calls:
            return None

        tool_names = [tc.get("name", "unknown") for tc in tool_calls]
        unique_tools = list(dict.fromkeys(tool_names))
        name = _slugify(conversation_summary[:60]) or "auto-skill"

        procedure_lines = []
        for i, tc in enumerate(tool_calls, 1):
            args_summary = ", ".join(f"{k}={v!r}" for k, v in list(tc.get("arguments", {}).items())[:3])
            procedure_lines.append(f"{i}. Call `{tc.get('name', '?')}` with {args_summary or 'no args'}")

        content = SKILL_TEMPLATE.format(
            name=name,
            description=conversation_summary[:120],
            title=conversation_summary[:80],
            when_to_use=f"When you need to perform tasks involving: {', '.join(unique_tools)}",
            procedure="\n".join(procedure_lines),
            pitfalls="- Review generated output before applying",
            verification="- Confirm expected results after execution",
        )
        return content

    def save_skill(self, name: str, content: str) -> None:
        """Save a skill to ~/.anvil/skills/{name}/SKILL.md."""
        skill_dir = self._skills_dir / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_path = skill_dir / "SKILL.md"
        skill_path.write_text(content, encoding="utf-8")
        logger.info("Saved skill: %s -> %s", name, skill_path)


def _slugify(text: str) -> str:
    """Convert text to a URL-friendly slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")[:60]
