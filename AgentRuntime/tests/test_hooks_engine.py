"""Tests for the hooks engine."""

import json
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from anvil_agent.hooks.engine import HookEvent, HooksEngine


class TestHookEvent:
    def test_all_events_exist(self):
        assert HookEvent.PRE_TOOL_USE.value == "PreToolUse"
        assert HookEvent.POST_TOOL_USE.value == "PostToolUse"
        assert HookEvent.SESSION_START.value == "SessionStart"
        assert HookEvent.SESSION_END.value == "SessionEnd"
        assert HookEvent.STOP.value == "Stop"
        assert HookEvent.TASK_CREATED.value == "TaskCreated"
        assert HookEvent.TASK_COMPLETED.value == "TaskCompleted"
        assert HookEvent.TEAMMATE_IDLE.value == "TeammateIdle"


class TestHooksEngineMatching:
    def test_no_matcher_always_matches(self):
        engine = HooksEngine()
        hook: dict[str, Any] = {"event": "PreToolUse", "command": "echo ok"}
        assert engine._matches(hook, {"tool_name": "bash"}) is True

    def test_tool_name_matcher(self):
        engine = HooksEngine()
        hook: dict[str, Any] = {"matcher": {"tool_name": "bash"}}
        assert engine._matches(hook, {"tool_name": "bash"}) is True
        assert engine._matches(hook, {"tool_name": "read_file"}) is False

    def test_regex_matcher(self):
        engine = HooksEngine()
        hook: dict[str, Any] = {"matcher": {"regex": "rm.*-rf"}}
        assert engine._matches(hook, {"command": "rm -rf /"}) is True
        assert engine._matches(hook, {"command": "ls -la"}) is False

    def test_invalid_regex_returns_false(self):
        engine = HooksEngine()
        hook: dict[str, Any] = {"matcher": {"regex": "[invalid"}}
        assert engine._matches(hook, {"command": "anything"}) is False


class TestHooksEngineLoadConfig:
    def test_load_config(self):
        engine = HooksEngine()
        config = [{"event": "PreToolUse", "command": "echo hi"}]
        engine.load_config(config)
        assert len(engine._hooks) == 1

    def test_load_from_files_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            hooks_dir = Path(tmp) / ".claude" / "hooks"
            hooks_dir.mkdir(parents=True)
            hook_file = hooks_dir / "test.json"
            hook_file.write_text(json.dumps([
                {"event": "PreToolUse", "command": "echo test"}
            ]))

            engine = HooksEngine()
            engine.load_from_files(project_dir=Path(tmp))
            assert len(engine._hooks) == 1
            assert engine._hooks[0]["command"] == "echo test"

    def test_load_from_files_single_hook_dict(self):
        with tempfile.TemporaryDirectory() as tmp:
            hooks_dir = Path(tmp) / ".claude" / "hooks"
            hooks_dir.mkdir(parents=True)
            hook_file = hooks_dir / "single.json"
            hook_file.write_text(json.dumps(
                {"event": "Stop", "command": "echo done"}
            ))

            engine = HooksEngine()
            engine.load_from_files(project_dir=Path(tmp))
            assert len(engine._hooks) == 1


class TestHooksEngineRun:
    @pytest.mark.asyncio
    async def test_command_hook_allows(self):
        engine = HooksEngine([
            {"event": "PreToolUse", "type": "command", "command": "exit 0"}
        ])
        allowed, output = await engine.run(HookEvent.PRE_TOOL_USE, {"tool_name": "bash"})
        assert allowed is True

    @pytest.mark.asyncio
    async def test_command_hook_blocks(self):
        engine = HooksEngine([
            {"event": "PreToolUse", "type": "command", "command": "exit 2"}
        ])
        allowed, output = await engine.run(HookEvent.PRE_TOOL_USE, {"tool_name": "bash"})
        assert allowed is False

    @pytest.mark.asyncio
    async def test_command_hook_captures_stdout(self):
        engine = HooksEngine([
            {"event": "PreToolUse", "type": "command", "command": "echo 'hook output'"}
        ])
        allowed, output = await engine.run(HookEvent.PRE_TOOL_USE, {"tool_name": "bash"})
        assert allowed is True
        assert output is not None
        assert "hook output" in output

    @pytest.mark.asyncio
    async def test_no_matching_hooks_allows(self):
        engine = HooksEngine([
            {"event": "SessionStart", "type": "command", "command": "exit 2"}
        ])
        allowed, output = await engine.run(HookEvent.PRE_TOOL_USE, {"tool_name": "bash"})
        assert allowed is True
        assert output is None

    @pytest.mark.asyncio
    async def test_empty_hooks_allows(self):
        engine = HooksEngine()
        allowed, output = await engine.run(HookEvent.PRE_TOOL_USE, {"tool_name": "bash"})
        assert allowed is True

    @pytest.mark.asyncio
    async def test_matcher_filters_hooks(self):
        engine = HooksEngine([
            {
                "event": "PreToolUse",
                "type": "command",
                "command": "exit 2",
                "matcher": {"tool_name": "delete_file"},
            }
        ])
        # Should NOT block bash (matcher doesn't match)
        allowed, _ = await engine.run(HookEvent.PRE_TOOL_USE, {"tool_name": "bash"})
        assert allowed is True

        # Should block delete_file
        allowed, _ = await engine.run(HookEvent.PRE_TOOL_USE, {"tool_name": "delete_file"})
        assert allowed is False
