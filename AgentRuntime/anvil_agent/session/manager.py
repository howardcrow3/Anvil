"""Session persistence and management."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from anvil_agent.models.types import ChatMessage

if TYPE_CHECKING:
    from anvil_agent.session.search import SessionSearchDB

logger = logging.getLogger(__name__)

SESSIONS_DIR = Path.home() / ".anvil" / "sessions"


class SessionMetadata(BaseModel):
    """Metadata about a session."""

    id: str
    name: str = ""
    created_at: str = ""
    last_active: str = ""
    message_count: int = 0


class SessionManager:
    """Manages conversation sessions as JSONL files."""

    def __init__(
        self,
        sessions_dir: Path = SESSIONS_DIR,
        search_db: SessionSearchDB | None = None,
    ) -> None:
        self._dir = sessions_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._search_db = search_db

    def create(self, name: str = "", session_id: str | None = None) -> str:
        """Create a new session and return its ID."""
        session_id = session_id or str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        meta = SessionMetadata(
            id=session_id,
            name=name,
            created_at=now,
            last_active=now,
        )
        meta_path = self._dir / f"{session_id}.meta.json"
        meta_path.write_text(meta.model_dump_json(indent=2))
        # Create empty JSONL file
        (self._dir / f"{session_id}.jsonl").touch()
        return session_id

    def append_message(self, session_id: str, message: ChatMessage) -> None:
        """Append a message to the session log."""
        path = self._dir / f"{session_id}.jsonl"
        timestamp = datetime.now(timezone.utc).isoformat()
        entry = {
            "role": message.role,
            "content": message.content,
            "timestamp": timestamp,
        }
        if message.tool_calls:
            entry["tool_calls"] = [tc.model_dump() for tc in message.tool_calls]
        if message.tool_call_id:
            entry["tool_call_id"] = message.tool_call_id

        with path.open("a") as f:
            f.write(json.dumps(entry) + "\n")

        # Index for full-text search
        if self._search_db and message.content:
            try:
                asyncio.get_event_loop().create_task(
                    self._search_db.index_message(
                        session_id, message.role, message.content, timestamp
                    )
                )
            except RuntimeError:
                logger.debug("No event loop for search indexing")

        # Update metadata
        self._update_meta(session_id)

    def load_messages(self, session_id: str) -> list[ChatMessage]:
        """Load all messages from a session."""
        path = self._dir / f"{session_id}.jsonl"
        if not path.exists():
            return []

        messages: list[ChatMessage] = []
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                # Skip non-message entries (e.g. Swift session metadata)
                if "role" not in data:
                    continue
                data.pop("timestamp", None)
                messages.append(ChatMessage(**data))
            except (json.JSONDecodeError, TypeError, Exception):
                continue
        return messages

    def list_sessions(self) -> list[dict[str, Any]]:
        """List all sessions with metadata."""
        sessions = []
        for meta_path in sorted(self._dir.glob("*.meta.json"), reverse=True):
            try:
                meta = SessionMetadata(**json.loads(meta_path.read_text()))
                sessions.append(meta.model_dump())
            except Exception:
                continue
        return sessions

    def auto_name(self, session_id: str, first_message: str) -> None:
        """Auto-name a session based on the first user message."""
        name = first_message[:80].strip()
        if len(first_message) > 80:
            name += "..."
        meta_path = self._dir / f"{session_id}.meta.json"
        if meta_path.exists():
            meta = SessionMetadata(**json.loads(meta_path.read_text()))
            if not meta.name:
                meta.name = name
                meta_path.write_text(meta.model_dump_json(indent=2))

    def _update_meta(self, session_id: str) -> None:
        meta_path = self._dir / f"{session_id}.meta.json"
        if not meta_path.exists():
            return
        meta = SessionMetadata(**json.loads(meta_path.read_text()))
        meta.last_active = datetime.now(timezone.utc).isoformat()
        jsonl_path = self._dir / f"{session_id}.jsonl"
        if jsonl_path.exists():
            meta.message_count = sum(1 for line in jsonl_path.read_text().splitlines() if line.strip())
        meta_path.write_text(meta.model_dump_json(indent=2))
