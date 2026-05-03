"""FTS5-backed session search."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

try:
    import aiosqlite

    HAS_AIOSQLITE = True
except ImportError:
    HAS_AIOSQLITE = False

logger = logging.getLogger(__name__)

STATE_DB_PATH = Path.home() / ".anvil" / "state.db"


class SessionSearchDB:
    """SQLite FTS5 index for searching across session messages."""

    def __init__(self, db_path: Path = STATE_DB_PATH) -> None:
        self._db_path = db_path
        self._db: Any = None

    async def initialize(self) -> None:
        """Create the database and FTS5 virtual table."""
        if not HAS_AIOSQLITE:
            logger.warning("aiosqlite not installed, session search disabled")
            return
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self._db_path))
        await self._db.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS sessions_fts USING fts5(
                session_id,
                role,
                content,
                timestamp,
                tokenize='porter'
            )
            """
        )
        await self._db.commit()
        logger.info("Session search DB initialized at %s", self._db_path)

    async def index_message(
        self, session_id: str, role: str, content: str, timestamp: str
    ) -> None:
        """Add a message to the FTS5 index."""
        if not self._db or not content:
            return
        await self._db.execute(
            "INSERT INTO sessions_fts(session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
            (session_id, role, content, timestamp),
        )
        await self._db.commit()

    async def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Full-text search across indexed sessions."""
        if not self._db:
            return []

        results: list[dict[str, Any]] = []
        try:
            async with self._db.execute(
                """
                SELECT session_id, role, content, timestamp, rank
                FROM sessions_fts
                WHERE sessions_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (query, limit),
            ) as cursor:
                async for row in cursor:
                    results.append({
                        "session_id": row[0],
                        "role": row[1],
                        "content": row[2],
                        "timestamp": row[3],
                        "rank": row[4],
                    })
        except Exception as e:
            logger.warning("Session search error: %s", e)

        return results

    async def summarize_results(
        self, query: str, results: list[dict[str, Any]]
    ) -> str:
        """Placeholder for LLM-based summarization of search results."""
        if not results:
            return f"No results found for '{query}'."
        lines = [f"Found {len(results)} result(s) for '{query}':"]
        for r in results:
            snippet = r["content"][:120]
            lines.append(f"  [{r['role']}] {snippet}")
        return "\n".join(lines)

    async def close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None
