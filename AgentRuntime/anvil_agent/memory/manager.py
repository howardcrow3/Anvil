"""Memory management - loads context from project and global memory files."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

GLOBAL_MEMORY_DIR = Path.home() / ".anvil" / "memory"
MEMORY_TRUNCATE_LINES = 200


class MemoryManager:
    """Loads and manages agent memory from project and global files."""

    def __init__(self, project_dir: Path | None = None) -> None:
        self._project_dir = project_dir
        self._global_dir = GLOBAL_MEMORY_DIR
        self._global_dir.mkdir(parents=True, exist_ok=True)

    # ── Context Loading ──────────────────────────────────────────

    def load_context(self) -> str:
        """Load all relevant memory context as a string for the system prompt."""
        parts: list[str] = []

        # Walk directory tree for CLAUDE.md files
        for path, content in self._walk_claude_files():
            parts.append(f"# Project Instructions ({path})\n{content}")

        # Load rules
        for name, content in self._load_rules():
            parts.append(f"# Rule: {name}\n{content}")

        # Load global memory
        global_memory = self._global_dir / "MEMORY.md"
        if global_memory.exists():
            try:
                content = global_memory.read_text(encoding="utf-8")
                parts.append(f"# Global Memory\n{content}")
            except Exception as e:
                logger.warning("Failed to read global memory: %s", e)

        # Load user profile
        user_md = self._global_dir / "USER.md"
        if user_md.exists():
            try:
                content = user_md.read_text(encoding="utf-8")
                parts.append(f"# User Profile\n{content}")
            except Exception as e:
                logger.warning("Failed to read USER.md: %s", e)

        return "\n\n".join(parts)

    def _walk_claude_files(self) -> list[tuple[str, str]]:
        """Walk up directory tree collecting CLAUDE.md files."""
        results: list[tuple[str, str]] = []

        if not self._project_dir:
            return results

        current = self._project_dir
        home = Path.home()
        while current != home and current != current.parent:
            for name in ["CLAUDE.md", ".claude/CLAUDE.md"]:
                path = current / name
                if path.exists():
                    try:
                        content = path.read_text(encoding="utf-8")
                        results.append((str(path), content))
                    except Exception as e:
                        logger.warning("Failed to read %s: %s", path, e)
            current = current.parent

        return results

    def _load_rules(self) -> list[tuple[str, str]]:
        """Load .claude/rules/*.md files."""
        results: list[tuple[str, str]] = []
        if not self._project_dir:
            return results

        rules_dir = self._project_dir / ".claude" / "rules"
        if rules_dir.is_dir():
            for f in sorted(rules_dir.glob("*.md")):
                try:
                    results.append((f.name, f.read_text(encoding="utf-8")))
                except Exception as e:
                    logger.warning("Failed to read rule %s: %s", f.name, e)

        return results

    # ── System Prompt Addition ───────────────────────────────────

    def get_system_prompt_addition(self) -> str:
        """Return all memory as a formatted string for the system prompt.

        MEMORY.md is truncated to 200 lines.
        """
        parts: list[str] = []

        # MEMORY.md (truncated)
        memory_path = self._global_dir / "MEMORY.md"
        if memory_path.exists():
            try:
                lines = memory_path.read_text(encoding="utf-8").splitlines()
                if len(lines) > MEMORY_TRUNCATE_LINES:
                    lines = lines[:MEMORY_TRUNCATE_LINES]
                    lines.append("... (truncated)")
                parts.append("# Auto Memory\n" + "\n".join(lines))
            except Exception as e:
                logger.warning("Failed to read MEMORY.md: %s", e)

        # Other topic files
        for topic_path in sorted(self._global_dir.glob("*.md")):
            if topic_path.name == "MEMORY.md":
                continue
            try:
                content = topic_path.read_text(encoding="utf-8")
                parts.append(f"# Memory: {topic_path.stem}\n{content}")
            except Exception as e:
                logger.warning("Failed to read %s: %s", topic_path.name, e)

        return "\n\n".join(parts)

    # ── Topic Management ─────────────────────────────────────────

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

    def list_topics(self) -> list[str]:
        """List all .md files in the memory directory."""
        return sorted(
            f.stem for f in self._global_dir.glob("*.md") if f.is_file()
        )

    def delete_topic(self, topic: str) -> bool:
        """Remove a topic file. Returns True if deleted."""
        path = self._global_dir / f"{topic}.md"
        if path.exists():
            path.unlink()
            logger.info("Deleted memory topic: %s", topic)
            return True
        return False

    def search_memory(self, query: str) -> list[dict]:
        """Case-insensitive text search across all memory files."""
        results: list[dict] = []
        query_lower = query.lower()

        for topic_path in sorted(self._global_dir.glob("*.md")):
            if not topic_path.is_file():
                continue
            try:
                for i, line in enumerate(
                    topic_path.read_text(encoding="utf-8").splitlines(), 1
                ):
                    if query_lower in line.lower():
                        results.append({
                            "topic": topic_path.stem,
                            "line": i,
                            "content": line.strip(),
                        })
            except Exception:
                continue

        return results

    def save_auto_memory(self, key: str, content: str) -> None:
        """Save an auto-generated memory with 'auto_' prefix."""
        self.save_memory(f"auto_{key}", content)
