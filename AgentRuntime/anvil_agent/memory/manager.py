"""Memory management - loads context from project and global memory files."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

GLOBAL_MEMORY_DIR = Path.home() / ".anvil" / "memory"


class MemoryManager:
    """Loads and manages agent memory from project and global files."""

    def __init__(self, project_dir: Path | None = None) -> None:
        self._project_dir = project_dir
        self._global_dir = GLOBAL_MEMORY_DIR
        self._global_dir.mkdir(parents=True, exist_ok=True)

    def load_context(self) -> str:
        """Load all relevant memory context as a string for the system prompt."""
        parts: list[str] = []

        # Load project CLAUDE.md
        if self._project_dir:
            for name in ["CLAUDE.md", ".claude/CLAUDE.md"]:
                path = self._project_dir / name
                if path.exists():
                    try:
                        content = path.read_text(encoding="utf-8")
                        parts.append(f"# Project Instructions ({name})\n{content}")
                    except Exception as e:
                        logger.warning("Failed to read %s: %s", path, e)

        # Load global memory
        global_memory = self._global_dir / "MEMORY.md"
        if global_memory.exists():
            try:
                content = global_memory.read_text(encoding="utf-8")
                parts.append(f"# Global Memory\n{content}")
            except Exception as e:
                logger.warning("Failed to read global memory: %s", e)

        return "\n\n".join(parts)

    def save_memory(self, topic: str, content: str) -> None:
        """Save a memory to a topic file."""
        path = self._global_dir / f"{topic}.md"
        path.write_text(content, encoding="utf-8")
        logger.info("Saved memory to %s", path)

    def load_topic(self, topic: str) -> str | None:
        """Load a specific topic file."""
        path = self._global_dir / f"{topic}.md"
        if path.exists():
            return path.read_text(encoding="utf-8")
        return None
