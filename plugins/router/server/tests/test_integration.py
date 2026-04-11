"""Integration tests — end-to-end scenarios combining multiple modules."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import yaml

from server.lib.http_client import FireResult
from server.lib.storage import load_failures
from server.tools.fire import hooks_fire
from server.tools.recovery import hooks_recover
from server.tools.registry import hooks_register, hooks_unregister


class TestRegisterThenFire:
    """Register hooks, then fire them and verify the full chain."""

    @pytest.mark.asyncio
    async def test_register_and_fire_blocking(self, hooks_yaml: Path, proj_yaml: Path):
        """Register a blocking hook, fire it, verify success summary."""
        with patch("server.lib.storage._HOOKS_FILE", hooks_yaml):
            hooks_register(
                trigger_tool="proj_init",
                target_tool="perms_setup",
                server="perms",
                param_mapping='{"path": "${result.path}"}',
                blocking=True,
            )

        mock_result = FireResult(hook_id="hook-001", status_code=200, body="ok")
        captured_params = {}

        async def mock_post(*, hook_id, url, target_tool, params):
            captured_params.update(params)
            return mock_result

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.tools.fire.post_hook", side_effect=mock_post),
        ):
            source = json.dumps({"result": {"path": "/home/user/project"}})
            result = await hooks_fire("proj_init", source_result=source)

        data = json.loads(result)
        assert data["hooks_fired"] == 1
        assert data["errors"] == []
        assert captured_params["path"] == "/home/user/project"

    @pytest.mark.asyncio
    async def test_register_fire_unregister_fire(self, hooks_yaml: Path):
        """Hook fires before unregister, does not fire after."""
        with patch("server.lib.storage._HOOKS_FILE", hooks_yaml):
            hooks_register(
                trigger_tool="trigger_a",
                target_tool="target_b",
                server="srv",
                blocking=True,
            )

        mock_result = FireResult(hook_id="hook-001", status_code=200, body="ok")
        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch(
                "server.tools.fire._fire_single", new_callable=AsyncMock, return_value=mock_result
            ),
        ):
            result1 = await hooks_fire("trigger_a")
        assert json.loads(result1)["hooks_fired"] == 1

        # Unregister
        with patch("server.lib.storage._HOOKS_FILE", hooks_yaml):
            hooks_unregister("hook-001")

        # Fire again — no hooks should match
        with patch("server.lib.storage._HOOKS_FILE", hooks_yaml):
            result2 = await hooks_fire("trigger_a")
        assert json.loads(result2)["hooks_fired"] == 0


class TestRegisterConditionThenFire:
    """Register with condition, toggle config, fire — verifies the full path."""

    @pytest.mark.asyncio
    async def test_register_condition_toggle_fire(self, hooks_yaml: Path, proj_yaml: Path):
        """Register hook with condition, fire with False (skipped), then True (fires)."""
        with patch("server.lib.storage._HOOKS_FILE", hooks_yaml):
            hooks_register(
                trigger_tool="proj_init",
                target_tool="todoist_sync",
                server="todoist",
                condition="sync.todoist.enabled",
                blocking=True,
            )

        # Fire with condition False — skipped
        proj_yaml.write_text(yaml.dump({"sync": {"todoist": {"enabled": False}}}))
        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.conditions._PROJ_CONFIG_PATH", proj_yaml),
        ):
            r1 = await hooks_fire("proj_init")
        d1 = json.loads(r1)
        assert d1["hooks_fired"] == 0

        # Fire with condition True — fires, then unregister and verify empty
        proj_yaml.write_text(yaml.dump({"sync": {"todoist": {"enabled": True}}}))
        mock_result = FireResult(hook_id="hook-001", status_code=200, body="ok")
        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.conditions._PROJ_CONFIG_PATH", proj_yaml),
            patch(
                "server.tools.fire._fire_single", new_callable=AsyncMock, return_value=mock_result
            ),
        ):
            r2 = await hooks_fire("proj_init")
        d2 = json.loads(r2)
        assert d2["hooks_fired"] == 1

        # Unregister and verify firing returns 0
        with patch("server.lib.storage._HOOKS_FILE", hooks_yaml):
            hooks_unregister("hook-001")
        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.conditions._PROJ_CONFIG_PATH", proj_yaml),
        ):
            r3 = await hooks_fire("proj_init")
        assert json.loads(r3)["hooks_fired"] == 0


class TestFailureRecoveryIntegration:
    """Register, fire (fail), then recover."""

    @pytest.mark.asyncio
    async def test_fire_fail_recover_success(self, hooks_yaml: Path, failures_yaml: Path):
        """Blocking hook fails, failure is logged, retry succeeds."""
        with patch("server.lib.storage._HOOKS_FILE", hooks_yaml):
            hooks_register(
                trigger_tool="proj_init",
                target_tool="perms_setup",
                server="perms",
                blocking=True,
            )

        # Fire with HTTP 500 — should log failure
        fail_result = FireResult(hook_id="hook-001", status_code=500, body="error")
        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.storage._FAILURES_FILE", failures_yaml),
            patch(
                "server.tools.fire._fire_single", new_callable=AsyncMock, return_value=fail_result
            ),
        ):
            fire_result = await hooks_fire("proj_init")

        data = json.loads(fire_result)
        assert len(data["errors"]) == 1

        # Verify failure was logged
        failures = load_failures(failures_yaml)
        assert len(failures) == 1
        assert failures[0]["hook_id"] == "hook-001"

        # Retry — this time success
        success_result = FireResult(hook_id="hook-001", status_code=200, body="ok")
        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.storage._FAILURES_FILE", failures_yaml),
            patch(
                "server.tools.recovery.post_hook",
                new_callable=AsyncMock,
                return_value=success_result,
            ),
        ):
            recover_result = await hooks_recover(hook_id="hook-001")

        rdata = json.loads(recover_result)
        assert rdata["retried"] == 1
        assert rdata["succeeded"] == 1
        assert rdata["still_failed"] == 0

        # Failures file should be empty after successful retry
        remaining = load_failures(failures_yaml)
        assert len(remaining) == 0

    @pytest.mark.asyncio
    async def test_clear_failures(self, hooks_yaml: Path, failures_yaml: Path):
        """Clear all failures without retrying."""
        with patch("server.lib.storage._HOOKS_FILE", hooks_yaml):
            hooks_register(
                trigger_tool="t",
                target_tool="u",
                server="s",
                blocking=True,
            )

        fail_result = FireResult(hook_id="hook-001", status_code=500, body="err")
        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.storage._FAILURES_FILE", failures_yaml),
            patch(
                "server.tools.fire._fire_single", new_callable=AsyncMock, return_value=fail_result
            ),
        ):
            await hooks_fire("t")

        with patch("server.lib.storage._FAILURES_FILE", failures_yaml):
            clear_result = await hooks_recover(clear=True)

        cdata = json.loads(clear_result)
        assert cdata["cleared"] == 1
        assert cdata["retried"] == 0

    @pytest.mark.asyncio
    async def test_recover_list_mode(self, failures_yaml: Path):
        """With no hook_id and no clear, recover returns the failure list."""
        entries = [
            {"hook_id": "hook-001", "error": "timeout"},
            {"hook_id": "hook-002", "error": "refused"},
        ]
        failures_yaml.write_text(yaml.dump(entries, default_flow_style=False))

        with patch("server.lib.storage._FAILURES_FILE", failures_yaml):
            result = await hooks_recover()

        data = json.loads(result)
        assert len(data) == 2
        assert data[0]["hook_id"] == "hook-001"

    @pytest.mark.asyncio
    async def test_recover_no_matching_entries(self, failures_yaml: Path):
        """Retry with a hook_id that has no failures."""
        with patch("server.lib.storage._FAILURES_FILE", failures_yaml):
            result = await hooks_recover(hook_id="hook-999")
        data = json.loads(result)
        assert data["retried"] == 0
        assert "No failure entries found" in data.get("message", "")


class TestMultipleFailuresRecovery:
    """Register multiple hooks, fire both failing, recover selectively."""

    @pytest.mark.asyncio
    async def test_selective_recovery_by_hook_id(self, hooks_yaml: Path, failures_yaml: Path):
        """Two hooks fail, recover only one by hook_id, verify the other remains."""
        with patch("server.lib.storage._HOOKS_FILE", hooks_yaml):
            hooks_register(trigger_tool="t", target_tool="u1", server="s", blocking=True)
            hooks_register(trigger_tool="t", target_tool="u2", server="s", blocking=True)

        fail1 = FireResult(hook_id="hook-001", status_code=500, body="err")
        fail2 = FireResult(hook_id="hook-002", status_code=500, body="err")

        call_count = 0

        async def mock_fire(hook, source):
            nonlocal call_count
            call_count += 1
            return fail1 if hook.id == "hook-001" else fail2

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.storage._FAILURES_FILE", failures_yaml),
            patch("server.tools.fire._fire_single", side_effect=mock_fire),
        ):
            await hooks_fire("t")

        failures = load_failures(failures_yaml)
        assert len(failures) == 2

        # Recover only hook-001
        success = FireResult(hook_id="hook-001", status_code=200, body="ok")
        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.storage._FAILURES_FILE", failures_yaml),
            patch(
                "server.tools.recovery.post_hook",
                new_callable=AsyncMock,
                return_value=success,
            ),
        ):
            r = await hooks_recover(hook_id="hook-001")

        rdata = json.loads(r)
        assert rdata["retried"] == 1
        assert rdata["succeeded"] == 1

        # hook-002 failure still present
        remaining = load_failures(failures_yaml)
        assert len(remaining) == 1
        assert remaining[0]["hook_id"] == "hook-002"
