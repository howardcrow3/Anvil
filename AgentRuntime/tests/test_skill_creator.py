"""Tests for anvil_agent.skills.creator."""

from __future__ import annotations

import pytest

from anvil_agent.skills.creator import SkillCreator, _slugify


class TestSkillCreator:
    """Tests for SkillCreator."""

    def test_should_create_skill_true(self):
        creator = SkillCreator()
        assert creator.should_create_skill(5, success=True) is True
        assert creator.should_create_skill(10, success=True) is True

    def test_should_create_skill_false_low_count(self):
        creator = SkillCreator()
        assert creator.should_create_skill(3, success=True) is False
        assert creator.should_create_skill(0, success=True) is False
        assert creator.should_create_skill(4, success=True) is False

    def test_should_create_skill_false_failure(self):
        creator = SkillCreator()
        assert creator.should_create_skill(5, success=False) is False
        assert creator.should_create_skill(10, success=False) is False

    @pytest.mark.asyncio
    async def test_create_skill_content(self):
        creator = SkillCreator()
        tool_calls = [
            {"name": "read_file", "arguments": {"path": "/tmp/a.py"}},
            {"name": "write_file", "arguments": {"path": "/tmp/b.py", "content": "x"}},
            {"name": "run_command", "arguments": {"cmd": "pytest"}},
        ]
        content = await creator.create_skill("Refactor module imports", tool_calls)
        assert content is not None
        assert "---" in content
        assert "name:" in content
        assert "version: 1.0.0" in content
        assert "## Procedure" in content
        assert "`read_file`" in content
        assert "`write_file`" in content
        assert "`run_command`" in content
        assert "## When to Use" in content
        assert "## Pitfalls" in content
        assert "## Verification" in content

    @pytest.mark.asyncio
    async def test_create_skill_empty_tool_calls(self):
        creator = SkillCreator()
        result = await creator.create_skill("Some summary", [])
        assert result is None

    def test_save_skill(self, tmp_path):
        creator = SkillCreator(skills_dir=tmp_path)
        creator.save_skill("my-skill", "# Test Skill\nContent here")
        skill_file = tmp_path / "my-skill" / "SKILL.md"
        assert skill_file.exists()
        assert skill_file.read_text() == "# Test Skill\nContent here"

    def test_slugify(self):
        assert _slugify("Hello World") == "hello-world"
        assert _slugify("  spaces  around  ") == "spaces-around"
        assert _slugify("Special!@#Characters") == "specialcharacters"
        assert _slugify("under_scores_here") == "under-scores-here"
        assert _slugify("multiple---dashes") == "multiple-dashes"
        assert _slugify("") == ""
        assert _slugify("UPPER CASE") == "upper-case"
