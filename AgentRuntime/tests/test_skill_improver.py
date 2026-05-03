"""Tests for anvil_agent.skills.improver."""

from __future__ import annotations

import pytest

from anvil_agent.skills.improver import (
    SkillImprover,
    _bump_version,
    _extract_procedure_steps,
    _extract_tool_names_from_steps,
    _replace_procedure,
)

SAMPLE_SKILL = """\
---
name: test-skill
description: A test skill
version: 1.0.0
---
# Test Skill

## When to Use
When testing.

## Procedure
1. Call `read_file` with path=/tmp/a.py
2. Call `write_file` with path=/tmp/b.py

## Pitfalls
- None

## Verification
- Check output"""


class TestSkillImprover:
    """Tests for SkillImprover."""

    @pytest.mark.asyncio
    async def test_no_active_skill_returns_none(self):
        improver = SkillImprover()
        result = await improver.check_improvement()
        assert result is None

    @pytest.mark.asyncio
    async def test_no_steps_returns_none(self):
        improver = SkillImprover()
        improver.set_active_skill("test-skill", SAMPLE_SKILL)
        result = await improver.check_improvement()
        assert result is None

    @pytest.mark.asyncio
    async def test_matching_steps_returns_none(self):
        improver = SkillImprover()
        improver.set_active_skill("test-skill", SAMPLE_SKILL)
        improver.record_actual_steps([
            {"name": "read_file", "arguments": {"path": "/tmp/a.py"}},
            {"name": "write_file", "arguments": {"path": "/tmp/b.py"}},
        ])
        result = await improver.check_improvement()
        assert result is None

    @pytest.mark.asyncio
    async def test_divergent_steps_returns_improved(self):
        improver = SkillImprover()
        improver.set_active_skill("test-skill", SAMPLE_SKILL)
        improver.record_actual_steps([
            {"name": "read_file", "arguments": {"path": "/tmp/a.py"}},
            {"name": "run_command", "arguments": {"cmd": "pytest"}},
            {"name": "write_file", "arguments": {"path": "/tmp/b.py"}},
        ])
        result = await improver.check_improvement()
        assert result is not None
        assert "`run_command`" in result
        assert "version: 1.0.1" in result

    def test_apply_improvement(self, tmp_path):
        improver = SkillImprover(skills_dir=tmp_path)
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text(SAMPLE_SKILL)

        improved = SAMPLE_SKILL.replace("version: 1.0.0", "version: 1.0.1")
        improver.apply_improvement("test-skill", improved)

        assert "version: 1.0.1" in skill_file.read_text()

    def test_clear(self):
        improver = SkillImprover()
        improver.set_active_skill("test-skill", SAMPLE_SKILL)
        improver.record_actual_steps([{"name": "read_file"}])
        improver.clear()
        assert improver._active_skill_name is None
        assert improver._active_skill_content is None
        assert improver._actual_steps == []

    def test_bump_version(self):
        assert "version: 1.0.1" in _bump_version("version: 1.0.0")
        assert "version: 2.3.6" in _bump_version("version: 2.3.5")
        assert "version: 0.0.2" in _bump_version("version: 0.0.1")

    def test_extract_procedure_steps(self):
        steps = _extract_procedure_steps(SAMPLE_SKILL)
        assert len(steps) == 2
        assert "read_file" in steps[0]
        assert "write_file" in steps[1]

    def test_extract_procedure_steps_empty(self):
        content = "# No procedure section here\nJust some text."
        assert _extract_procedure_steps(content) == []

    def test_extract_tool_names(self):
        steps = [
            "1. Call `read_file` with path=/tmp/a.py",
            "2. Call `write_file` with path=/tmp/b.py",
            "3. Call `run_command` with cmd=pytest",
        ]
        names = _extract_tool_names_from_steps(steps)
        assert names == ["read_file", "write_file", "run_command"]

    def test_extract_tool_names_no_backticks(self):
        steps = ["1. Do something without backtick names"]
        assert _extract_tool_names_from_steps(steps) == []

    def test_replace_procedure(self):
        new_proc = "1. Call `new_tool` with no args"
        result = _replace_procedure(SAMPLE_SKILL, new_proc)
        assert "## Procedure" in result
        assert "`new_tool`" in result
        # Old procedure lines should be gone
        assert "Call `read_file` with path=/tmp/a.py" not in result
        # Other sections preserved
        assert "## Pitfalls" in result
        assert "## Verification" in result
