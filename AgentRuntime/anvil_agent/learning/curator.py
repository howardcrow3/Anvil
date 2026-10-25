"""Skill curator: lifecycle housekeeping for agent-created skills.

Adapted from Hermes Agent's curator (MIT, Nous Research — see THIRD_PARTY_NOTICES.md). Deterministic
transitions only by default (active -> stale -> archived into ``.archive/``); never deletes; skips
pinned skills and anything the user wrote. The optional LLM consolidation pass is off by default.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any

from anvil_agent.skills.usage import ARCHIVE_DIRNAME, USER_SKILLS_DIR, SkillUsageStore

DAY = 86400.0

CONSOLIDATION_PROMPT = """\
You are the skill curator. Review the agent-created skills listed below and tidy the library:
merge near-duplicates into one umbrella skill (patch the best one, then it is fine to leave the others
for the archive step), tighten overlong descriptions, and fix skills whose steps contradict each other.
Use skills_list, skill_view and skill_manage only. Never touch pinned skills. Do not delete anything.
Finish with a one-paragraph summary of what you changed.

Candidates:
{candidates}
"""


class Curator:
    def __init__(
        self,
        skills_dir: Path | None = None,
        stale_after_days: float = 30,
        archive_after_days: float = 90,
        interval_hours: float = 24 * 7,
        min_idle_hours: float = 2,
        enabled: bool = True,
        consolidate: bool = False,
    ) -> None:
        self.dir = Path(skills_dir) if skills_dir else USER_SKILLS_DIR
        self.usage = SkillUsageStore(self.dir)
        self.stale_days, self.archive_days = stale_after_days, archive_after_days
        self.interval = interval_hours * 3600
        self.min_idle = min_idle_hours * 3600
        self.enabled, self.consolidate = enabled, consolidate
        self.state_path = self.dir / ".curator_state.json"

    # -- state ------------------------------------------------------------------

    def state(self) -> dict[str, Any]:
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_state(self, **kw: Any) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        s = {**self.state(), **kw}
        self.state_path.write_text(json.dumps(s, indent=1), encoding="utf-8")

    def should_run(self, now: float | None = None, last_activity: float | None = None) -> bool:
        now = now or time.time()
        if not self.enabled or self.state().get("paused"):
            return False
        if now - self.state().get("last_run_at", 0) < self.interval:
            return False
        return last_activity is None or now - last_activity >= self.min_idle

    # -- deterministic pass --------------------------------------------------------

    def candidates(self) -> list[str]:
        if not self.dir.is_dir():
            return []
        out = []
        for d in sorted(self.dir.iterdir()):
            if d.name.startswith(".") or not (d / "SKILL.md").is_file():
                continue
            if self.usage.get(d.name).get("pinned") or not self.usage.is_agent_created(d.name):
                continue
            out.append(d.name)
        return out

    def apply_automatic_transitions(self, now: float | None = None) -> dict[str, list[str]]:
        now = now or time.time()
        result: dict[str, list[str]] = {"marked_stale": [], "archived": [], "reactivated": []}
        for name in self.candidates():
            rec = self.usage.get(name)
            anchor = rec.get("last_used_at") or rec.get("created_at") or (self.dir / name / "SKILL.md").stat().st_mtime
            idle_days = (now - anchor) / DAY
            if idle_days >= self.archive_days:
                self.archive(name)
                result["archived"].append(name)
            elif idle_days >= self.stale_days and rec.get("state") != "stale":
                self.usage.update(name, state="stale")
                result["marked_stale"].append(name)
            elif idle_days < self.stale_days and rec.get("state") == "stale":
                self.usage.update(name, state="active")
                result["reactivated"].append(name)
        return result

    def archive(self, name: str) -> Path:
        src = self.dir / name
        dest_root = self.dir / ARCHIVE_DIRNAME
        dest_root.mkdir(parents=True, exist_ok=True)
        dest = dest_root / name
        if dest.exists():
            dest = dest_root / f"{name}-{int(time.time())}"
        shutil.move(str(src), str(dest))
        self.usage.update(name, state="archived", archived_at=time.time())
        return dest

    def restore(self, name: str) -> bool:
        src = self.dir / ARCHIVE_DIRNAME / name
        if not src.is_dir() or (self.dir / name).exists():
            return False
        shutil.move(str(src), str(self.dir / name))
        self.usage.update(name, state="active", last_used_at=time.time())
        return True

    def pin(self, name: str, pinned: bool = True) -> None:
        self.usage.pin(name, pinned)

    # -- orchestration ----------------------------------------------------------------

    async def run(self, spawn_consolidation=None, now: float | None = None) -> dict[str, Any]:
        """Run now. ``spawn_consolidation(prompt)`` is an async callable returning a summary (only used if enabled)."""
        report: dict[str, Any] = {"transitions": self.apply_automatic_transitions(now), "consolidation": None}
        if self.consolidate and spawn_consolidation and (names := self.candidates()):
            listing = "\n".join(f"- {n}" for n in names)
            try:
                report["consolidation"] = await spawn_consolidation(CONSOLIDATION_PROMPT.format(candidates=listing))
            except Exception as exc:  # noqa: BLE001
                report["consolidation"] = f"failed: {exc}"
        self._save_state(last_run_at=now or time.time(), last_report=report)
        return report

    def status(self) -> dict[str, Any]:
        s = self.state()
        counts: dict[str, int] = {}
        for n in self.candidates():
            st = self.usage.get(n).get("state", "active")
            counts[st] = counts.get(st, 0) + 1
        archived = len(list((self.dir / ARCHIVE_DIRNAME).iterdir())) if (self.dir / ARCHIVE_DIRNAME).is_dir() else 0
        return {"enabled": self.enabled, "paused": bool(s.get("paused")), "last_run_at": s.get("last_run_at"),
                "last_report": s.get("last_report"), "counts": counts, "archived": archived, "consolidate": self.consolidate}

    def set_paused(self, paused: bool) -> None:
        self._save_state(paused=paused)
