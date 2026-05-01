"""Git operations service."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class GitService:
    """Provides structured access to common git operations."""

    def __init__(self, repo_path: Path) -> None:
        self._repo = repo_path

    async def get_status(self) -> dict[str, Any]:
        """Return structured git status."""
        branch = await self.get_branch()
        raw = await self._run_git("status", "--porcelain")

        modified: list[str] = []
        added: list[str] = []
        deleted: list[str] = []
        untracked: list[str] = []

        for line in raw.splitlines():
            if len(line) < 3:
                continue
            status = line[:2]
            filepath = line[3:]

            if status == "??":
                untracked.append(filepath)
            elif "D" in status:
                deleted.append(filepath)
            elif "A" in status:
                added.append(filepath)
            else:
                modified.append(filepath)

        return {
            "branch": branch,
            "modified": modified,
            "added": added,
            "deleted": deleted,
            "untracked": untracked,
        }

    async def get_diff(self, staged: bool = False) -> str:
        """Return git diff output."""
        if staged:
            return await self._run_git("diff", "--staged")
        return await self._run_git("diff")

    async def get_log(self, n: int = 10) -> list[dict[str, str]]:
        """Return recent commits as structured data."""
        raw = await self._run_git(
            "log", f"-{n}",
            "--format=%H%x00%s%x00%an%x00%aI",
        )
        entries: list[dict[str, str]] = []
        for line in raw.splitlines():
            if not line.strip():
                continue
            parts = line.split("\x00")
            if len(parts) >= 4:
                entries.append({
                    "hash": parts[0],
                    "message": parts[1],
                    "author": parts[2],
                    "date": parts[3],
                })
        return entries

    async def get_branch(self) -> str:
        """Return the current branch name."""
        return (await self._run_git("branch", "--show-current")).strip()

    async def _run_git(self, *args: str) -> str:
        """Run a git command in the repo directory and return stdout."""
        proc = await asyncio.create_subprocess_exec(
            "git", *args,
            cwd=str(self._repo),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            err_msg = stderr.decode().strip()
            logger.warning("git %s failed: %s", " ".join(args), err_msg)
            return ""
        return stdout.decode()
