"""Skills Hub - browse and search all available skills."""

from __future__ import annotations

from typing import Any

from anvil_agent.skills.loader import SkillLoader


class SkillsHub:
    """Central hub for browsing and searching skills from all sources."""

    def __init__(self, loader: SkillLoader) -> None:
        self._loader = loader

    def browse(self) -> list[dict[str, Any]]:
        """List all skills with name, description, source, and version."""
        return self._loader.get_all_skills()

    def search(self, query: str) -> list[dict[str, Any]]:
        """Keyword search across skill names and descriptions."""
        query_lower = query.lower()
        results: list[dict[str, Any]] = []
        for skill in self._loader.get_all_skills():
            name = skill.get("name", "").lower()
            description = skill.get("description", "").lower()
            if query_lower in name or query_lower in description:
                results.append(skill)
        return results
