"""Tests for anvil_agent.skills.hub and anvil_agent.skills.loader."""

from __future__ import annotations

from pathlib import Path

from anvil_agent.skills.hub import SkillsHub
from anvil_agent.skills.loader import SkillLoader, _parse_frontmatter

SAMPLE_SKILL_MD = """\
---
name: deploy-app
description: Deploy the application to production
version: 1.2.0
---
# Deploy App

## Procedure
1. Call `run_command` with cmd=deploy
"""

SAMPLE_SKILL_MD_2 = """\
---
name: run-tests
description: Run the full test suite
version: 0.5.0
---
# Run Tests

## Procedure
1. Call `run_command` with cmd=pytest
"""


def _make_user_skill(base_dir: Path, name: str, content: str) -> None:
    """Helper to create a skill directory with SKILL.md."""
    skill_dir = base_dir / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")


class TestSkillsHub:
    """Tests for SkillsHub."""

    def test_browse_empty(self):
        loader = SkillLoader(project_dir=None)
        hub = SkillsHub(loader)
        assert hub.browse() == []

    def test_browse_with_skills(self, tmp_path):
        project = tmp_path / "project"
        skills_dir = project / ".claude" / "skills" / "deploy-app"
        skills_dir.mkdir(parents=True)
        (skills_dir / "SKILL.md").write_text(SAMPLE_SKILL_MD)

        loader = SkillLoader(project_dir=project)
        loader.load_project_skills()
        hub = SkillsHub(loader)

        results = hub.browse()
        assert len(results) == 1
        assert results[0]["name"] == "deploy-app"
        assert results[0]["source"] == "project"
        assert results[0]["version"] == "1.2.0"

    def test_search_match(self, tmp_path):
        project = tmp_path / "project"
        skills_dir = project / ".claude" / "skills" / "deploy-app"
        skills_dir.mkdir(parents=True)
        (skills_dir / "SKILL.md").write_text(SAMPLE_SKILL_MD)

        loader = SkillLoader(project_dir=project)
        loader.load_project_skills()
        hub = SkillsHub(loader)

        results = hub.search("deploy")
        assert len(results) == 1
        assert results[0]["name"] == "deploy-app"

    def test_search_match_description(self, tmp_path):
        project = tmp_path / "project"
        skills_dir = project / ".claude" / "skills" / "deploy-app"
        skills_dir.mkdir(parents=True)
        (skills_dir / "SKILL.md").write_text(SAMPLE_SKILL_MD)

        loader = SkillLoader(project_dir=project)
        loader.load_project_skills()
        hub = SkillsHub(loader)

        results = hub.search("production")
        assert len(results) == 1
        assert results[0]["name"] == "deploy-app"

    def test_search_no_match(self, tmp_path):
        project = tmp_path / "project"
        skills_dir = project / ".claude" / "skills" / "deploy-app"
        skills_dir.mkdir(parents=True)
        (skills_dir / "SKILL.md").write_text(SAMPLE_SKILL_MD)

        loader = SkillLoader(project_dir=project)
        loader.load_project_skills()
        hub = SkillsHub(loader)

        results = hub.search("nonexistent")
        assert len(results) == 0

    def test_search_case_insensitive(self, tmp_path):
        project = tmp_path / "project"
        skills_dir = project / ".claude" / "skills" / "deploy-app"
        skills_dir.mkdir(parents=True)
        (skills_dir / "SKILL.md").write_text(SAMPLE_SKILL_MD)

        loader = SkillLoader(project_dir=project)
        loader.load_project_skills()
        hub = SkillsHub(loader)

        results = hub.search("DEPLOY")
        assert len(results) == 1
        assert results[0]["name"] == "deploy-app"


class TestSkillLoaderUserSkills:
    """Tests for SkillLoader user skills and helpers."""

    def test_load_user_skills(self, tmp_path, monkeypatch):
        _make_user_skill(tmp_path, "deploy-app", SAMPLE_SKILL_MD)
        monkeypatch.setattr(
            "anvil_agent.skills.loader.USER_SKILLS_DIR", tmp_path
        )
        loader = SkillLoader(project_dir=None)
        loader.load_user_skills()
        skills = loader.get_all_skills()
        assert len(skills) == 1
        assert skills[0]["name"] == "deploy-app"
        assert skills[0]["source"] == "user"

    def test_get_all_skills(self, tmp_path, monkeypatch):
        # Set up project skills
        project = tmp_path / "project"
        proj_skill = project / ".claude" / "skills" / "deploy-app"
        proj_skill.mkdir(parents=True)
        (proj_skill / "SKILL.md").write_text(SAMPLE_SKILL_MD)

        # Set up user skills
        user_dir = tmp_path / "user_skills"
        _make_user_skill(user_dir, "run-tests", SAMPLE_SKILL_MD_2)
        monkeypatch.setattr(
            "anvil_agent.skills.loader.USER_SKILLS_DIR", user_dir
        )

        loader = SkillLoader(project_dir=project)
        loader.load_project_skills()
        loader.load_user_skills()

        skills = loader.get_all_skills()
        assert len(skills) == 2
        names = {s["name"] for s in skills}
        assert names == {"deploy-app", "run-tests"}

    def test_parse_frontmatter(self):
        meta = _parse_frontmatter(SAMPLE_SKILL_MD)
        assert meta["name"] == "deploy-app"
        assert meta["description"] == "Deploy the application to production"
        assert meta["version"] == "1.2.0"

    def test_parse_frontmatter_missing(self):
        meta = _parse_frontmatter("# No frontmatter here\nJust content.")
        assert meta == {}

    def test_skills_command_registered(self):
        loader = SkillLoader(project_dir=None)
        cmd = loader.get_command("/skills")
        assert cmd is not None
        assert cmd["builtin"] is True
        assert "skills" in cmd["description"].lower()
