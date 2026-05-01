"""Git repository detection."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class GitDetector:
    """Detect whether a directory is inside a git repository."""

    @staticmethod
    async def is_git_repo(path: Path) -> bool:
        """Check if path is inside a git work tree."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "git", "rev-parse", "--is-inside-work-tree",
                cwd=str(path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await proc.communicate()
            return proc.returncode == 0 and stdout.strip() == b"true"
        except Exception:
            return False

    @staticmethod
    async def get_repo_root(path: Path) -> Path | None:
        """Return the root of the git repository, or None."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "git", "rev-parse", "--show-toplevel",
                cwd=str(path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await proc.communicate()
            if proc.returncode == 0:
                return Path(stdout.decode().strip())
        except Exception:
            pass
        return None
