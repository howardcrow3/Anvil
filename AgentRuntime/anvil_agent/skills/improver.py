"""Skill self-improvement - compares expected vs actual execution."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

USER_SKILLS_DIR = Path.home() / ".anvil" / "skills"


class SkillImprover:
    """Tracks skill execution and suggests improvements."""

    def __init__(self, skills_dir: Path = USER_SKILLS_DIR) -> None:
        self._skills_dir = skills_dir
        self._active_skill_name: str | None = None
        self._active_skill_content: str | None = None
        self._actual_steps: list[dict[str, Any]] = []

    def set_active_skill(self, skill_name: str, skill_content: str) -> None:
        """Track which skill is currently being executed."""
        self._active_skill_name = skill_name
        self._active_skill_content = skill_content
        self._actual_steps = []

    def record_actual_steps(self, tool_calls: list[dict[str, Any]]) -> None:
        """Record the tool calls the agent actually made."""
        self._actual_steps.extend(tool_calls)

    async def check_improvement(self) -> str | None:
        """Compare expected procedure vs actual steps.

        Returns improved SKILL.md content if the actual steps diverged
        significantly from the documented procedure, or None if no
        improvement is needed.
        """
        if not self._active_skill_name or not self._active_skill_content:
            return None
        if not self._actual_steps:
            return None

        expected_steps = _extract_procedure_steps(self._active_skill_content)
        actual_tool_names = [s.get("name", "") for s in self._actual_steps]

        if not expected_steps:
            return None

        # Simple divergence check: if actual steps differ from expected
        expected_tools = _extract_tool_names_from_steps(expected_steps)
        if expected_tools == actual_tool_names:
            return None

        # Build improved procedure from actual steps
        new_procedure_lines = []
        for i, step in enumerate(self._actual_steps, 1):
            args_summary = ", ".join(
                f"{k}={v!r}"
                for k, v in list(step.get("arguments", {}).items())[:3]
            )
            new_procedure_lines.append(
                f"{i}. Call `{step.get('name', '?')}` with {args_summary or 'no args'}"
            )
        new_procedure = "\n".join(new_procedure_lines)

        # Patch the skill content
        improved = _replace_procedure(self._active_skill_content, new_procedure)
        improved = _bump_version(improved)

        return improved

    def apply_improvement(self, skill_name: str, improved_content: str) -> None:
        """Write the improved SKILL.md back to disk."""
        skill_path = self._skills_dir / skill_name / "SKILL.md"
        if skill_path.exists():
            skill_path.write_text(improved_content, encoding="utf-8")
            logger.info("Improved skill: %s", skill_name)

    def clear(self) -> None:
        """Reset tracking state."""
        self._active_skill_name = None
        self._active_skill_content = None
        self._actual_steps = []


def _extract_procedure_steps(content: str) -> list[str]:
    """Extract lines from the ## Procedure section."""
    lines = content.split("\n")
    in_section = False
    steps: list[str] = []
    for line in lines:
        if line.strip().startswith("## Procedure"):
            in_section = True
            continue
        if in_section and line.strip().startswith("## "):
            break
        if in_section and line.strip():
            steps.append(line.strip())
    return steps


def _extract_tool_names_from_steps(steps: list[str]) -> list[str]:
    """Extract tool names from procedure step lines like '1. Call `tool_name` ...'."""
    names: list[str] = []
    for step in steps:
        m = re.search(r"`(\w+)`", step)
        if m:
            names.append(m.group(1))
    return names


def _replace_procedure(content: str, new_procedure: str) -> str:
    """Replace the ## Procedure section content."""
    lines = content.split("\n")
    result: list[str] = []
    in_section = False
    replaced = False
    for line in lines:
        if line.strip().startswith("## Procedure"):
            result.append(line)
            result.append(new_procedure)
            in_section = True
            replaced = True
            continue
        if in_section and line.strip().startswith("## "):
            in_section = False
        if not in_section:
            result.append(line)
    if not replaced:
        result.append("\n## Procedure\n" + new_procedure)
    return "\n".join(result)


def _bump_version(content: str) -> str:
    """Increment the patch version in YAML frontmatter."""
    def _inc_patch(match: re.Match[str]) -> str:
        parts = match.group(1).split(".")
        if len(parts) == 3:
            parts[2] = str(int(parts[2]) + 1)
        return f"version: {'.'.join(parts)}"

    return re.sub(r"version:\s*([\d.]+)", _inc_patch, content, count=1)
