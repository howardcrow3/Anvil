"""Tests for the permission manager."""

import asyncio

import pytest

from anvil_agent.permissions import PermissionManager, PermissionMode, READ_ONLY_TOOLS


class TestPermissionMode:
    def test_enum_values(self):
        assert PermissionMode.ASK.value == "ask"
        assert PermissionMode.ACCEPT_EDITS.value == "accept_edits"
        assert PermissionMode.TRUST.value == "trust"


class TestPermissionManagerCheckSync:
    def test_trust_allows_everything(self):
        pm = PermissionManager(mode=PermissionMode.TRUST)
        assert pm.check_sync("bash") == "allow"
        assert pm.check_sync("write_file") == "allow"
        assert pm.check_sync("read_file") == "allow"

    def test_ask_asks_everything(self):
        pm = PermissionManager(mode=PermissionMode.ASK)
        assert pm.check_sync("bash") == "ask"
        assert pm.check_sync("write_file") == "ask"
        assert pm.check_sync("read_file") == "ask"

    def test_accept_edits_allows_read_only(self):
        pm = PermissionManager(mode=PermissionMode.ACCEPT_EDITS)
        for tool in READ_ONLY_TOOLS:
            assert pm.check_sync(tool) == "allow", f"{tool} should be auto-allowed"

    def test_accept_edits_asks_for_writes(self):
        pm = PermissionManager(mode=PermissionMode.ACCEPT_EDITS)
        assert pm.check_sync("bash") == "ask"
        assert pm.check_sync("write_file") == "ask"
        assert pm.check_sync("edit_file") == "ask"

    def test_deny_list_overrides_trust(self):
        pm = PermissionManager(mode=PermissionMode.TRUST)
        pm.set_overrides(deny_list=["bash"])
        assert pm.check_sync("bash") == "deny"
        assert pm.check_sync("read_file") == "allow"

    def test_allow_list_overrides_ask(self):
        pm = PermissionManager(mode=PermissionMode.ASK)
        pm.set_overrides(allow_list=["bash"])
        assert pm.check_sync("bash") == "allow"
        assert pm.check_sync("write_file") == "ask"

    def test_deny_takes_precedence_over_allow(self):
        pm = PermissionManager(mode=PermissionMode.TRUST)
        pm.set_overrides(allow_list=["bash"], deny_list=["bash"])
        assert pm.check_sync("bash") == "deny"

    def test_mode_setter(self):
        pm = PermissionManager(mode=PermissionMode.ASK)
        assert pm.mode == PermissionMode.ASK
        pm.mode = PermissionMode.TRUST
        assert pm.mode == PermissionMode.TRUST
        assert pm.check_sync("bash") == "allow"


class TestPermissionManagerAsync:
    @pytest.mark.asyncio
    async def test_respond_approves(self):
        pm = PermissionManager(mode=PermissionMode.ASK)

        async def approve_after_delay():
            await asyncio.sleep(0.05)
            pm.respond("req-1", True)

        asyncio.create_task(approve_after_delay())
        result = await pm.request_permission("req-1", "bash", {"command": "ls"})
        assert result is True

    @pytest.mark.asyncio
    async def test_respond_denies(self):
        pm = PermissionManager(mode=PermissionMode.ASK)

        async def deny_after_delay():
            await asyncio.sleep(0.05)
            pm.respond("req-2", False)

        asyncio.create_task(deny_after_delay())
        result = await pm.request_permission("req-2", "bash", {"command": "rm -rf /"})
        assert result is False
