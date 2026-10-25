"""Skill usage sidecar (``<skills_dir>/.usage.json``), after Hermes Agent's skill_usage (MIT, Nous Research)."""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any

USER_SKILLS_DIR = Path.home() / ".anvil" / "skills"
ARCHIVE_DIRNAME = ".archive"
_FM = re.compile(r"\A---\n(.*?)\n---", re.S)


def parse_frontmatter(text: str) -> dict[str, str]:
    m = _FM.match(text)
    out: dict[str, str] = {}
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                out[k.strip()] = v.strip()
    return out


class SkillUsageStore:
    def __init__(self, skills_dir: Path | None = None) -> None:
        self.dir = Path(skills_dir) if skills_dir else USER_SKILLS_DIR
        self.path = self.dir / ".usage.json"

    def _load(self) -> dict[str, dict[str, Any]]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self, data: dict[str, dict[str, Any]]) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.dir, prefix=".usage.", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1)
        os.replace(tmp, self.path)

    def get(self, name: str) -> dict[str, Any]:
        return self._load().get(name, {})

    def all(self) -> dict[str, dict[str, Any]]:
        return self._load()

    def update(self, name: str, **fields: Any) -> None:
        data = self._load()
        rec = data.setdefault(name, {"created_at": time.time(), "view_count": 0, "use_count": 0, "patch_count": 0, "state": "active"})
        rec.update(fields)
        self._save(data)

    def bump(self, name: str, counter: str) -> None:
        data = self._load()
        rec = data.setdefault(name, {"created_at": time.time(), "view_count": 0, "use_count": 0, "patch_count": 0, "state": "active"})
        rec[counter] = rec.get(counter, 0) + 1
        rec["last_used_at"] = time.time()
        if rec.get("state") == "stale":
            rec["state"] = "active"
        self._save(data)

    def forget(self, name: str) -> None:
        data = self._load()
        if data.pop(name, None) is not None:
            self._save(data)

    def is_agent_created(self, name: str) -> bool:
        if self.get(name).get("created_by") == "agent":
            return True
        skill = self.dir / name / "SKILL.md"
        try:
            return parse_frontmatter(skill.read_text(encoding="utf-8")).get("created_by") in ("agent", "anvil-auto")
        except OSError:
            return False

    def pin(self, name: str, pinned: bool = True) -> None:
        self.update(name, pinned=pinned)
