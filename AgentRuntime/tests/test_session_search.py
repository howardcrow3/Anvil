"""Tests for session search (FTS5) and session search tool."""

import pytest

from anvil_agent.session.search import SessionSearchDB
from anvil_agent.models.types import ToolResult
from anvil_agent.tools.session_search_tool import SessionSearchTool


# ---------------------------------------------------------------------------
# SessionSearchDB
# ---------------------------------------------------------------------------


class TestSessionSearchDB:
    @pytest.mark.asyncio
    async def test_initialize_creates_db(self, tmp_path):
        db_path = tmp_path / "test.db"
        db = SessionSearchDB(db_path=db_path)
        await db.initialize()
        assert db_path.exists()
        await db.close()

    @pytest.mark.asyncio
    async def test_index_and_search(self, tmp_path):
        db = SessionSearchDB(db_path=tmp_path / "test.db")
        await db.initialize()

        await db.index_message("s1", "user", "How do I install Python?", "2025-01-01T00:00:00")
        await db.index_message("s1", "assistant", "Use brew install python.", "2025-01-01T00:01:00")
        await db.index_message("s2", "user", "Tell me about Rust lang.", "2025-01-02T00:00:00")

        results = await db.search("python")
        assert len(results) >= 1
        contents = [r["content"] for r in results]
        assert any("Python" in c or "python" in c for c in contents)
        await db.close()

    @pytest.mark.asyncio
    async def test_search_empty_db(self, tmp_path):
        db = SessionSearchDB(db_path=tmp_path / "test.db")
        await db.initialize()
        results = await db.search("anything")
        assert results == []
        await db.close()

    @pytest.mark.asyncio
    async def test_search_ranking(self, tmp_path):
        db = SessionSearchDB(db_path=tmp_path / "test.db")
        await db.initialize()

        # Message with "python" mentioned multiple times should rank higher.
        await db.index_message("s1", "user", "python python python", "2025-01-01T00:00:00")
        await db.index_message("s2", "user", "I once heard about python", "2025-01-01T00:01:00")

        results = await db.search("python")
        assert len(results) == 2
        # FTS5 rank is negative; lower (more negative) = better match.
        assert results[0]["rank"] <= results[1]["rank"]
        await db.close()

    @pytest.mark.asyncio
    async def test_index_empty_content(self, tmp_path):
        db = SessionSearchDB(db_path=tmp_path / "test.db")
        await db.initialize()

        await db.index_message("s1", "user", "", "2025-01-01T00:00:00")
        results = await db.search("anything")
        assert results == []
        await db.close()

    @pytest.mark.asyncio
    async def test_search_limit(self, tmp_path):
        db = SessionSearchDB(db_path=tmp_path / "test.db")
        await db.initialize()

        for i in range(5):
            await db.index_message(f"s{i}", "user", f"alpha keyword message {i}", f"2025-01-0{i+1}T00:00:00")

        results = await db.search("alpha", limit=2)
        assert len(results) == 2
        await db.close()

    @pytest.mark.asyncio
    async def test_summarize_results_with_results(self, tmp_path):
        db = SessionSearchDB(db_path=tmp_path / "test.db")
        await db.initialize()

        await db.index_message("s1", "user", "How do I deploy to production?", "2025-01-01T00:00:00")
        results = await db.search("deploy")
        summary = await db.summarize_results("deploy", results)

        assert "Found 1 result(s) for 'deploy'" in summary
        assert "[user]" in summary
        assert "deploy" in summary.lower()
        await db.close()

    @pytest.mark.asyncio
    async def test_summarize_results_empty(self, tmp_path):
        db = SessionSearchDB(db_path=tmp_path / "test.db")
        await db.initialize()

        summary = await db.summarize_results("nonexistent", [])
        assert summary == "No results found for 'nonexistent'."
        await db.close()

    @pytest.mark.asyncio
    async def test_search_without_init(self, tmp_path):
        db = SessionSearchDB(db_path=tmp_path / "test.db")
        # Deliberately skip initialize()
        results = await db.search("anything")
        assert results == []

    @pytest.mark.asyncio
    async def test_close(self, tmp_path):
        db = SessionSearchDB(db_path=tmp_path / "test.db")
        await db.initialize()
        await db.close()
        # After close, _db should be None
        assert db._db is None


# ---------------------------------------------------------------------------
# SessionSearchTool
# ---------------------------------------------------------------------------


class TestSessionSearchTool:
    @pytest.mark.asyncio
    async def test_tool_schema(self, tmp_path):
        db = SessionSearchDB(db_path=tmp_path / "test.db")
        tool = SessionSearchTool(search_db=db)

        assert tool.name == "session_search"
        assert "search" in tool.description.lower()
        schema = tool.to_schema()
        assert schema["name"] == "session_search"
        assert "query" in schema["parameters"]["properties"]
        assert "limit" in schema["parameters"]["properties"]
        assert "query" in schema["parameters"]["required"]

    @pytest.mark.asyncio
    async def test_execute_search(self, tmp_path):
        db = SessionSearchDB(db_path=tmp_path / "test.db")
        await db.initialize()
        await db.index_message("s1", "user", "Kubernetes pod networking", "2025-01-01T00:00:00")

        tool = SessionSearchTool(search_db=db)
        result = await tool.execute({"query": "kubernetes"})

        assert isinstance(result, ToolResult)
        assert not result.is_error
        assert "kubernetes" in result.content.lower() or "Kubernetes" in result.content
        await db.close()

    @pytest.mark.asyncio
    async def test_execute_no_query(self, tmp_path):
        db = SessionSearchDB(db_path=tmp_path / "test.db")
        tool = SessionSearchTool(search_db=db)

        result = await tool.execute({})
        assert result.is_error
        assert "No query" in result.content

    @pytest.mark.asyncio
    async def test_execute_with_limit(self, tmp_path):
        db = SessionSearchDB(db_path=tmp_path / "test.db")
        await db.initialize()

        for i in range(5):
            await db.index_message(f"s{i}", "user", f"delta topic message {i}", f"2025-01-0{i+1}T00:00:00")

        tool = SessionSearchTool(search_db=db)
        result = await tool.execute({"query": "delta", "limit": 2})

        assert not result.is_error
        assert "2 result(s)" in result.content
        await db.close()
