"""Plan persistence and management."""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

GLOBAL_PLANS_DIR = Path.home() / ".anvil" / "plans"


def _slugify(text: str) -> str:
    """Convert a description to a filesystem-safe slug."""
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_-]+", "-", slug)
    return slug[:60].strip("-")


class PlanManager:
    """Saves and loads implementation plans."""

    def save_plan(
        self,
        description: str,
        content: str,
        project_dir: Path | None = None,
    ) -> str:
        """Save a plan and return its ID (filename stem)."""
        timestamp = int(time.time())
        slug = _slugify(description) or "plan"
        plan_id = f"{slug}-{timestamp}"
        filename = f"{plan_id}.md"

        if project_dir:
            plans_dir = project_dir / ".claude" / "plans"
        else:
            plans_dir = GLOBAL_PLANS_DIR

        plans_dir.mkdir(parents=True, exist_ok=True)
        plan_path = plans_dir / filename
        plan_path.write_text(content, encoding="utf-8")
        logger.info("Saved plan %s to %s", plan_id, plan_path)
        return plan_id

    def load_plan(self, plan_id: str, project_dir: Path | None = None) -> str | None:
        """Load a plan by ID. Searches project dir first, then global."""
        search_dirs: list[Path] = []
        if project_dir:
            search_dirs.append(project_dir / ".claude" / "plans")
        search_dirs.append(GLOBAL_PLANS_DIR)

        for plans_dir in search_dirs:
            plan_path = plans_dir / f"{plan_id}.md"
            if plan_path.exists():
                return plan_path.read_text(encoding="utf-8")

        return None

    def list_plans(self, project_dir: Path | None = None) -> list[dict[str, Any]]:
        """List all available plans."""
        plans: list[dict[str, Any]] = []
        search_dirs: list[Path] = []

        if project_dir:
            search_dirs.append(project_dir / ".claude" / "plans")
        search_dirs.append(GLOBAL_PLANS_DIR)

        seen_ids: set[str] = set()
        for plans_dir in search_dirs:
            if not plans_dir.exists():
                continue
            for path in sorted(plans_dir.glob("*.md"), reverse=True):
                plan_id = path.stem
                if plan_id in seen_ids:
                    continue
                seen_ids.add(plan_id)

                # Extract description from slug (everything before the last -timestamp)
                parts = plan_id.rsplit("-", 1)
                description = parts[0].replace("-", " ") if len(parts) == 2 else plan_id

                stat = path.stat()
                created_at = datetime.fromtimestamp(
                    stat.st_ctime, tz=timezone.utc
                ).isoformat()

                plans.append({
                    "id": plan_id,
                    "description": description,
                    "created_at": created_at,
                    "path": str(path),
                })

        return plans
