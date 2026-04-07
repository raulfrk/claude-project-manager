"""Integration tests — end-to-end scenarios combining multiple modules."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import yaml

from server.lib.http_client import FireResult
from server.lib.models import HookRegistry
from server.lib.storage import load, load_failures, save
from server.lib.template import resolve_mapping
from server.tools.fire import hooks_fire
from server.tools.recovery import hooks_recover
from server.tools.registry import hooks_list, hooks_register, hooks_unregister


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


class TestConditionalFiring:
    """Hooks gated by proj.yaml conditions."""

    @pytest.mark.asyncio
    async def test_condition_gates_hook(self, hooks_yaml: Path, proj_yaml: Path):
        """Hook with condition only fires when proj.yaml has truthy value."""
        with patch("server.lib.storage._HOOKS_FILE", hooks_yaml):
            hooks_register(
                trigger_tool="proj_init",
                target_tool="todoist_sync",
                server="todoist",
                condition="sync.todoist.enabled",
                blocking=True,
            )

        # condition False — hook should be skipped
        proj_yaml.write_text(yaml.dump({"sync": {"todoist": {"enabled": False}}}))
        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.conditions._PROJ_CONFIG_PATH", proj_yaml),
        ):
            result = await hooks_fire("proj_init")
        assert json.loads(result)["skipped"] == 1
        assert json.loads(result)["hooks_fired"] == 0

        # condition True — hook should fire
        proj_yaml.write_text(yaml.dump({"sync": {"todoist": {"enabled": True}}}))
        mock_result = FireResult(hook_id="hook-001", status_code=200, body="ok")
        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.conditions._PROJ_CONFIG_PATH", proj_yaml),
            patch(
                "server.tools.fire._fire_single", new_callable=AsyncMock, return_value=mock_result
            ),
        ):
            result = await hooks_fire("proj_init")
        assert json.loads(result)["hooks_fired"] == 1
        assert json.loads(result)["skipped"] == 0


class TestListWithConditionStatus:
    """hooks_list returns condition_status resolved against live config."""

    def test_list_shows_status(self, hooks_yaml: Path, proj_yaml: Path):
        with patch("server.lib.storage._HOOKS_FILE", hooks_yaml):
            hooks_register(
                trigger_tool="proj_init",
                target_tool="perms_setup",
                server="perms",
            )
            hooks_register(
                trigger_tool="proj_init",
                target_tool="todoist_sync",
                server="todoist",
                condition="sync.todoist.enabled",
            )

        proj_yaml.write_text(yaml.dump({"sync": {"todoist": {"enabled": True}}}))

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.conditions._PROJ_CONFIG_PATH", proj_yaml),
        ):
            result = hooks_list()

        data = json.loads(result)
        statuses = {h["id"]: h["condition_status"] for h in data["hooks"]}
        assert statuses["hook-001"] == "always"
        assert statuses["hook-002"] == "active"


class TestCyclePreventionIntegration:
    """Verify cycle detection prevents registration in multi-step chains."""

    def test_three_node_cycle(self, hooks_yaml: Path):
        with patch("server.lib.storage._HOOKS_FILE", hooks_yaml):
            r1 = hooks_register(trigger_tool="A", target_tool="B", server="s")
            assert "Registered" in r1
            r2 = hooks_register(trigger_tool="B", target_tool="C", server="s")
            assert "Registered" in r2
            r3 = hooks_register(trigger_tool="C", target_tool="A", server="s")
            assert "Error" in r3
            assert "cycle" in r3.lower()

        reg = load(hooks_yaml)
        assert len(reg.hooks) == 2  # Third was rejected


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


class TestDepthLimitIntegration:
    """Verify max_depth setting prevents runaway cascades."""

    @pytest.mark.asyncio
    async def test_custom_max_depth(self, hooks_yaml: Path):
        """Custom maxdepth=1 in settings limits cascading."""
        reg = HookRegistry(
            hooks=[],
            settings={"max_depth": 1},
        )
        save(reg, hooks_yaml)

        with patch("server.lib.storage._HOOKS_FILE", hooks_yaml):
            hooks_register(trigger_tool="t", target_tool="u", server="s")

        with patch("server.lib.storage._HOOKS_FILE", hooks_yaml):
            result = await hooks_fire("t", depth=1)

        data = json.loads(result)
        assert data["depth_limited"] is True
        assert data["max_depth"] == 1


class TestServerEndpointResolution:
    """Verify server URL resolution from registry.servers."""

    @pytest.mark.asyncio
    async def test_server_url_used(self, hooks_yaml: Path):
        """When servers dict has a URL, it is passed to post_hook."""
        reg = HookRegistry(
            hooks=[],
            servers={"my-server": {"url": "http://localhost:9999"}},
        )
        save(reg, hooks_yaml)

        with patch("server.lib.storage._HOOKS_FILE", hooks_yaml):
            hooks_register(
                trigger_tool="t",
                target_tool="u",
                server="my-server",
                blocking=True,
            )

        captured_url = []

        async def mock_post(*, hook_id, url, target_tool, params):
            captured_url.append(url)
            return FireResult(hook_id=hook_id, status_code=200, body="ok")

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.tools.fire.post_hook", side_effect=mock_post),
        ):
            await hooks_fire("t")

        assert captured_url[0] == "http://localhost:9999"

    @pytest.mark.asyncio
    async def test_server_name_used_as_fallback(self, hooks_yaml: Path):
        """When servers dict has no URL, server name is used as-is."""
        with patch("server.lib.storage._HOOKS_FILE", hooks_yaml):
            hooks_register(
                trigger_tool="t",
                target_tool="u",
                server="raw-server-name",
                blocking=True,
            )

        captured_url = []

        async def mock_post(*, hook_id, url, target_tool, params):
            captured_url.append(url)
            return FireResult(hook_id=hook_id, status_code=200, body="ok")

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.tools.fire.post_hook", side_effect=mock_post),
        ):
            await hooks_fire("t")

        assert captured_url[0] == "raw-server-name"


class TestNestedParamMappingPipeline:
    """YAML → Hook.from_dict → resolve_mapping end-to-end for nested param_mapping."""

    def test_yaml_to_hook_to_resolve(self, tmp_path: Path):
        """Load a hook with nested param_mapping from YAML, resolve against source."""
        hooks_content = {
            "hooks": [
                {
                    "id": "test-nested-hook",
                    "trigger_tool": "some_tool",
                    "target_tool": "target_tool",
                    "server": "test",
                    "param_mapping": {
                        "tasks": [
                            {"content": "${title}", "projectId": "${project_id}"},
                        ],
                    },
                }
            ]
        }
        hooks_file = tmp_path / "hooks.yaml"
        hooks_file.write_text(yaml.dump(hooks_content, default_flow_style=False))

        # Load via HookRegistry.from_dict (same path as storage.load)
        raw = yaml.safe_load(hooks_file.read_text())
        registry = HookRegistry.from_dict(raw)
        hook = registry.hooks[0]

        assert hook.id == "test-nested-hook"
        assert isinstance(hook.param_mapping["tasks"], list)

        # Resolve the nested param_mapping
        source = {"title": "My Task", "project_id": "proj123"}
        result = resolve_mapping(hook.param_mapping, source)

        assert result == {
            "tasks": [{"content": "My Task", "projectId": "proj123"}],
        }
