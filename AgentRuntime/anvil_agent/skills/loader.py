"""Skill and slash-command discovery."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

USER_SKILLS_DIR = Path.home() / ".anvil" / "skills"


class SkillLoader:
    """Discovers built-in commands and project-defined skills/commands."""

    def __init__(self, project_dir: Path | None = None) -> None:
        self._project_dir = project_dir
        self._skills: dict[str, dict] = {}
        self._commands: dict[str, dict] = {}
        self._load_builtins()

    def _load_builtins(self) -> None:
        """Register built-in slash commands."""
        builtins = {
            "/help": "Show available commands",
            "/clear": "Clear conversation",
            "/compact": "Compress conversation history",
            "/resume": "Resume last session",
            "/settings": "Show current settings",
            "/plan": "Toggle planning mode",
            "/skills": "Browse/search skills (/skills browse, /skills search <query>)",
        }
        for name, description in builtins.items():
            self._commands[name] = {
                "name": name,
                "description": description,
                "builtin": True,
            }

    def load_project_skills(self) -> None:
        """Load skills from .claude/skills/*/SKILL.md and commands from .claude/commands/*.md."""
        if not self._project_dir:
            return

        # Load skills
        skills_dir = self._project_dir / ".claude" / "skills"
        if skills_dir.is_dir():
            for skill_dir in sorted(skills_dir.iterdir()):
                skill_file = skill_dir / "SKILL.md"
                if skill_file.is_file():
                    try:
                        content = skill_file.read_text(encoding="utf-8")
                        name = skill_dir.name
                        meta = _parse_frontmatter(content)
                        self._skills[name] = {
                            "name": name,
                            "path": str(skill_file),
                            "content": content,
                            "source": "project",
                            "description": meta.get("description", ""),
                            "version": meta.get("version", ""),
                        }
                        logger.debug("Loaded skill: %s", name)
                    except Exception as e:
                        logger.warning("Failed to load skill %s: %s", skill_dir.name, e)

        # Load custom commands
        commands_dir = self._project_dir / ".claude" / "commands"
        if commands_dir.is_dir():
            for cmd_file in sorted(commands_dir.glob("*.md")):
                try:
                    content = cmd_file.read_text(encoding="utf-8")
                    name = f"/{cmd_file.stem}"
                    self._commands[name] = {
                        "name": name,
                        "description": content.split("\n", 1)[0].strip("# ").strip(),
                        "builtin": False,
                        "content": content,
                    }
                    logger.debug("Loaded custom command: %s", name)
                except Exception as e:
                    logger.warning("Failed to load command %s: %s", cmd_file.name, e)

    def get_all_commands(self) -> list[dict]:
        """Return all commands (builtins + custom)."""
        return list(self._commands.values())

    def get_skill_context(self, name: str) -> str | None:
        """Return the SKILL.md content for injection into the system prompt."""
        skill = self._skills.get(name)
        if skill:
            return skill["content"]
        return None

    def load_user_skills(self) -> None:
        """Load skills from ~/.anvil/skills/*/SKILL.md."""
        if not USER_SKILLS_DIR.is_dir():
            return
        for skill_dir in sorted(USER_SKILLS_DIR.iterdir()):
            skill_file = skill_dir / "SKILL.md"
            if skill_file.is_file():
                try:
                    content = skill_file.read_text(encoding="utf-8")
                    name = skill_dir.name
                    meta = _parse_frontmatter(content)
                    self._skills[name] = {
                        "name": name,
                        "path": str(skill_file),
                        "content": content,
                        "source": "user",
                        "description": meta.get("description", ""),
                        "version": meta.get("version", ""),
                    }
                    logger.debug("Loaded user skill: %s", name)
                except Exception as e:
                    logger.warning("Failed to load user skill %s: %s", skill_dir.name, e)

    def get_all_skills(self) -> list[dict[str, Any]]:
        """Return all skills with source info from all sources."""
        results: list[dict[str, Any]] = []
        for name, skill in self._skills.items():
            results.append({
                "name": name,
                "description": skill.get("description", ""),
                "source": skill.get("source", "project"),
                "version": skill.get("version", ""),
            })
        return results

    def get_command(self, name: str) -> dict | None:
        """Look up a specific command by name."""
        return self._commands.get(name)


def _parse_frontmatter(content: str) -> dict[str, str]:
    """Parse YAML frontmatter from SKILL.md content."""
    meta: dict[str, str] = {}
    match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if not match:
        return meta
    for line in match.group(1).splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    return meta
