"""Skill and memory tools the agent (and the background reviewer) use to curate what it knows.

Narrow-waist surface adapted from Hermes Agent's skills_tool / skill_manager_tool / memory_tool
(MIT, Nous Research — see THIRD_PARTY_NOTICES.md). Skills are directories: ``<name>/SKILL.md`` plus
optional ``references|templates|scripts|assets``. Deletion is intentionally not offered; the curator
archives instead.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from anvil_agent.models.types import ToolResult
from anvil_agent.redact import redact
from anvil_agent.skills.usage import ARCHIVE_DIRNAME, USER_SKILLS_DIR, SkillUsageStore, parse_frontmatter
from anvil_agent.tools.base import Tool

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
SUBDIRS = ("references", "templates", "scripts", "assets")
MAX_SKILL_CHARS = 60_000
MEMORY_DIR = Path.home() / ".anvil" / "memory"
MEMORY_CHAR_LIMITS = {"memory": 8000, "user": 4000}
MEMORY_FILES = {"memory": "MEMORY.md", "user": "USER.md"}
ENTRY_SEP = "\n§\n"


def _out(payload: Any, is_error: bool = False) -> ToolResult:
    return ToolResult(id="", content=payload if isinstance(payload, str) else json.dumps(payload, indent=1), is_error=is_error)


class SkillTools:
    """Shared state for the three skill tools (usage store + read-before-write ledger)."""

    def __init__(self, skills_dir: Path | None = None) -> None:
        self.dir = Path(skills_dir) if skills_dir else USER_SKILLS_DIR
        self.usage = SkillUsageStore(self.dir)
        self.read: set[str] = set()

    def tools(self) -> list[Tool]:
        return [SkillsListTool(self), SkillViewTool(self), SkillManageTool(self)]

    def skill_path(self, name: str) -> Path:
        if not NAME_RE.match(name or ""):
            raise ValueError("invalid skill name (use lowercase letters, digits, '.', '_', '-')")
        return self.dir / name

    def safe_file(self, name: str, rel: str) -> Path:
        base = self.skill_path(name).resolve()
        target = (base / rel).resolve()
        if base != target and base not in target.parents:
            raise ValueError("path escapes the skill directory")
        parts = target.relative_to(base).parts
        if parts and parts[0] not in SUBDIRS and parts != ("SKILL.md",):
            raise ValueError(f"files must live under {', '.join(SUBDIRS)}")
        return target


class SkillsListTool(Tool):
    name = "skills_list"
    description = "List saved skills (name, description, usage). Use before creating a skill to avoid duplicates."
    parameters = {"type": "object", "properties": {}}

    def __init__(self, st: SkillTools) -> None:
        self._st = st

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        usage, rows = self._st.usage.all(), []
        if self._st.dir.is_dir():
            for d in sorted(self._st.dir.iterdir()):
                f = d / "SKILL.md"
                if d.name.startswith(".") or not f.is_file():
                    continue
                meta = parse_frontmatter(f.read_text(encoding="utf-8", errors="replace"))
                u = usage.get(d.name, {})
                rows.append({"name": d.name, "description": meta.get("description", ""), "state": u.get("state", "active"),
                             "pinned": bool(u.get("pinned")), "uses": u.get("use_count", 0) + u.get("view_count", 0),
                             "agent_created": self._st.usage.is_agent_created(d.name)})
        return _out({"skills": rows})


class SkillViewTool(Tool):
    name = "skill_view"
    description = "Read a skill's SKILL.md (or a supporting file via file_path). Required before patching a skill."
    parameters = {"type": "object", "properties": {"name": {"type": "string"}, "file_path": {"type": "string"}}, "required": ["name"]}

    def __init__(self, st: SkillTools) -> None:
        self._st = st

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        name = arguments.get("name", "")
        try:
            f = self._st.safe_file(name, arguments.get("file_path") or "SKILL.md")
            text = f.read_text(encoding="utf-8")
        except (ValueError, OSError) as exc:
            return _out({"error": str(exc)}, True)
        self._st.read.add(name)
        self._st.usage.bump(name, "view_count")
        return _out(text)


class SkillManageTool(Tool):
    name = "skill_manage"
    description = (
        "Create or maintain skills. Actions: create (name, content=full SKILL.md with frontmatter name/description), "
        "patch (name, old_string, new_string — must have viewed the skill first), edit (name, content — full rewrite, "
        "must have viewed first), write_file / remove_file (name, file_path under references|templates|scripts|assets). "
        "Prefer patching an existing skill over creating a near-duplicate."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["create", "patch", "edit", "write_file", "remove_file"]},
            "name": {"type": "string"}, "content": {"type": "string"}, "old_string": {"type": "string"},
            "new_string": {"type": "string"}, "file_path": {"type": "string"},
        },
        "required": ["action", "name"],
    }

    def __init__(self, st: SkillTools) -> None:
        self._st = st

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        st, action, name = self._st, arguments.get("action"), arguments.get("name", "")
        try:
            base = st.skill_path(name)
            skill_md = base / "SKILL.md"
            if action == "create":
                content = arguments.get("content", "")
                if skill_md.exists():
                    return _out({"error": f"skill '{name}' already exists; patch it instead"}, True)
                self._validate(content)
                content = self._tag_agent(redact(content))
                base.mkdir(parents=True, exist_ok=True)
                skill_md.write_text(content, encoding="utf-8")
                st.usage.update(name, created_by="agent", state="active")
                st.read.add(name)
                return _out({"created": name})
            if not skill_md.exists():
                return _out({"error": f"unknown skill '{name}'"}, True)
            if action in ("patch", "edit") and name not in st.read:
                return _out({"error": "view the skill with skill_view before modifying it"}, True)
            if action == "patch":
                old, new = arguments.get("old_string", ""), arguments.get("new_string", "")
                text = skill_md.read_text(encoding="utf-8")
                if not old or text.count(old) != 1:
                    return _out({"error": f"old_string must match exactly once (found {text.count(old) if old else 0})"}, True)
                updated = text.replace(old, redact(new))
                self._validate(updated)
                skill_md.write_text(updated, encoding="utf-8")
            elif action == "edit":
                content = redact(arguments.get("content", ""))
                self._validate(content)
                skill_md.write_text(content, encoding="utf-8")
            elif action == "write_file":
                f = st.safe_file(name, arguments.get("file_path", ""))
                if f == skill_md.resolve():
                    return _out({"error": "use edit/patch for SKILL.md"}, True)
                data = redact(arguments.get("content", ""))
                if len(data) > MAX_SKILL_CHARS:
                    return _out({"error": "file too large"}, True)
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text(data, encoding="utf-8")
            elif action == "remove_file":
                f = st.safe_file(name, arguments.get("file_path", ""))
                if f == skill_md.resolve() or not f.is_file():
                    return _out({"error": "not a removable supporting file"}, True)
                f.unlink()
            else:
                return _out({"error": f"unknown action '{action}'"}, True)
            st.usage.bump(name, "patch_count")
            return _out({"ok": True, "action": action, "name": name})
        except (ValueError, OSError) as exc:
            return _out({"error": str(exc)}, True)

    @staticmethod
    def _validate(content: str) -> None:
        if len(content) > MAX_SKILL_CHARS:
            raise ValueError("SKILL.md too large")
        meta = parse_frontmatter(content)
        if not meta.get("name") or not meta.get("description"):
            raise ValueError("SKILL.md needs YAML frontmatter with name and description")

    @staticmethod
    def _tag_agent(content: str) -> str:
        if "created_by:" in content.split("\n---", 1)[0]:
            return content
        return content.replace("\n---", "\ncreated_by: agent\n---", 1)


class MemoryTool(Tool):
    """Bounded curated memory: MEMORY.md (agent notes) and USER.md (about the user)."""

    name = "memory"
    description = (
        "Save durable facts across sessions. target='user' for who the user is and their preferences; "
        "target='memory' for environment facts, conventions and lessons. Actions: add, replace "
        "(old_text -> content), remove (old_text). Keep entries short; do not store task progress or secrets."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["add", "replace", "remove"]},
            "target": {"type": "string", "enum": ["memory", "user"]},
            "content": {"type": "string"}, "old_text": {"type": "string"},
        },
        "required": ["action", "target"],
    }

    def __init__(self, memory_dir: Path | None = None) -> None:
        self._dir = Path(memory_dir) if memory_dir else MEMORY_DIR

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        target = arguments.get("target")
        if target not in MEMORY_FILES:
            return _out({"error": "target must be 'memory' or 'user'"}, True)
        path, limit = self._dir / MEMORY_FILES[target], MEMORY_CHAR_LIMITS[target]
        self._dir.mkdir(parents=True, exist_ok=True)
        raw = path.read_text(encoding="utf-8") if path.exists() else ""
        entries = [e.strip() for e in raw.split("§") if e.strip()]
        action, content, old = arguments.get("action"), redact((arguments.get("content") or "").strip()), arguments.get("old_text") or ""
        if action == "add":
            if not content:
                return _out({"error": "content required"}, True)
            if content in entries:
                return _out({"ok": True, "note": "already present"})
            entries.append(content)
        else:
            hits = [i for i, e in enumerate(entries) if old and old in e]
            if len(hits) != 1:
                return _out({"error": f"old_text must match exactly one entry (matched {len(hits)})"}, True)
            if action == "replace":
                if not content:
                    return _out({"error": "content required"}, True)
                entries[hits[0]] = content
            elif action == "remove":
                del entries[hits[0]]
            else:
                return _out({"error": f"unknown action '{action}'"}, True)
        text = ENTRY_SEP.join(entries)
        if len(text) > limit:
            return _out({"error": f"{target} memory is full ({len(text)}/{limit} chars); replace or remove entries first", "entries": entries}, True)
        path.write_text(text + "\n" if text else "", encoding="utf-8")
        return _out({"ok": True, "entries": len(entries), "chars": len(text), "limit": limit})
