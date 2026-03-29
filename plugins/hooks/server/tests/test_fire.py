"""Tests for server.tools.fire — fire tool with mocked HTTP."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import yaml

from server.lib.http_client import FireResult
from server.lib.models import Hook, HookRegistry
from server.lib.storage import save
from server.tools.fire import _parse_verification_response, hooks_fire


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_registry(hooks: list[Hook], servers: dict | None = None, settings: dict | None = None):
    return HookRegistry(
        hooks=hooks,
        servers=servers or {},
        settings=settings or {},
    )


def _hook(
    hook_id: str,
    trigger: str,
    target: str,
    server: str = "srv",
    *,
    blocking: bool = False,
    condition: str | None = None,
    param_mapping: dict | None = None,
    verification: bool = False,
) -> Hook:
    return Hook(
        id=hook_id,
        trigger_tool=trigger,
        target_tool=target,
        server=server,
        blocking=blocking,
        condition=condition,
        param_mapping=param_mapping or {},
        verification=verification,
    )


# ── Tests ────────────────────────────────────────────────────────────────────


class TestHooksFire:
    @pytest.mark.asyncio
    async def test_no_matching_hooks(self, hooks_yaml: Path):
        save(HookRegistry(), hooks_yaml)
        with patch("server.lib.storage._HOOKS_FILE", hooks_yaml):
            result = await hooks_fire("nonexistent")
        data = json.loads(result)
        assert data["hooks_fired"] == 0
        assert data["skipped"] == 0
        assert data["errors"] == []

    @pytest.mark.asyncio
    async def test_fire_background_hook(self, hooks_yaml: Path):
        """Non-blocking hook fires in background; fire returns immediately."""
        reg = _make_registry([
            _hook("hook-001", "trigger_a", "target_b", blocking=False),
        ])
        save(reg, hooks_yaml)

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.tools.fire._fire_background") as mock_bg,
        ):
            result = await hooks_fire("trigger_a", source_result='{"key": "val"}')

        data = json.loads(result)
        assert data["hooks_fired"] == 1
        assert data["skipped"] == 0
        mock_bg.assert_called_once()

    @pytest.mark.asyncio
    async def test_fire_blocking_hook_success(self, hooks_yaml: Path):
        """Blocking hook awaited; successful result reported."""
        reg = _make_registry([
            _hook("hook-001", "trigger_a", "target_b", blocking=True),
        ])
        save(reg, hooks_yaml)
        mock_result = FireResult(hook_id="hook-001", status_code=200, body="ok")

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.tools.fire._fire_single", new_callable=AsyncMock, return_value=mock_result),
        ):
            result = await hooks_fire("trigger_a")

        data = json.loads(result)
        assert data["hooks_fired"] == 1
        assert data["errors"] == []
        assert data["results"] == [{"hook_id": "hook-001", "result": None}]

    @pytest.mark.asyncio
    async def test_fire_blocking_hook_success_with_result(self, hooks_yaml: Path):
        """Blocking hook with result field passes it through in summary."""
        reg = _make_registry([
            _hook("hook-001", "trigger_a", "target_b", blocking=True),
        ])
        save(reg, hooks_yaml)
        mock_result = FireResult(hook_id="hook-001", status_code=200, body="ok", result="created")

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.tools.fire._fire_single", new_callable=AsyncMock, return_value=mock_result),
        ):
            result = await hooks_fire("trigger_a")

        data = json.loads(result)
        assert data["hooks_fired"] == 1
        assert data["errors"] == []
        assert data["results"] == [{"hook_id": "hook-001", "result": "created"}]

    @pytest.mark.asyncio
    async def test_fire_blocking_hook_http_error(self, hooks_yaml: Path, failures_yaml: Path):
        """Blocking hook that fails logs failure and reports error."""
        reg = _make_registry([
            _hook("hook-001", "trigger_a", "target_b", blocking=True),
        ])
        save(reg, hooks_yaml)
        mock_result = FireResult(hook_id="hook-001", status_code=500, body="Internal Server Error")

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.storage._FAILURES_FILE", failures_yaml),
            patch("server.tools.fire._fire_single", new_callable=AsyncMock, return_value=mock_result),
        ):
            result = await hooks_fire("trigger_a")

        data = json.loads(result)
        assert data["hooks_fired"] == 1
        assert len(data["errors"]) == 1
        assert "hook-001" in data["errors"][0]["hook_id"]
        assert data["results"] == []

    @pytest.mark.asyncio
    async def test_fire_blocking_hook_exception(self, hooks_yaml: Path, failures_yaml: Path):
        """Blocking hook that raises exception is caught and logged."""
        reg = _make_registry([
            _hook("hook-001", "trigger_a", "target_b", blocking=True),
        ])
        save(reg, hooks_yaml)

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.storage._FAILURES_FILE", failures_yaml),
            patch(
                "server.tools.fire._fire_single",
                new_callable=AsyncMock,
                side_effect=ConnectionError("refused"),
            ),
        ):
            result = await hooks_fire("trigger_a")

        data = json.loads(result)
        assert data["hooks_fired"] == 1
        assert len(data["errors"]) == 1
        assert "Exception" in data["errors"][0]["error"]
        assert data["results"] == []

    @pytest.mark.asyncio
    async def test_fire_skips_false_condition(self, hooks_yaml: Path, proj_yaml: Path):
        """Hook with condition evaluating to False is skipped."""
        reg = _make_registry([
            _hook("hook-001", "trigger_a", "target_b", condition="feature.enabled"),
        ])
        save(reg, hooks_yaml)
        proj_yaml.write_text("")  # Empty config -> condition False

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.conditions._PROJ_CONFIG_PATH", proj_yaml),
        ):
            result = await hooks_fire("trigger_a")

        data = json.loads(result)
        assert data["hooks_fired"] == 0
        assert data["skipped"] == 1

    @pytest.mark.asyncio
    async def test_fire_depth_limit(self, hooks_yaml: Path):
        """Exceeding max_depth returns depth_limited response."""
        reg = _make_registry(
            [_hook("hook-001", "trigger_a", "target_b")],
            settings={"max_depth": 2},
        )
        save(reg, hooks_yaml)

        with patch("server.lib.storage._HOOKS_FILE", hooks_yaml):
            result = await hooks_fire("trigger_a", depth=2)

        data = json.loads(result)
        assert data["depth_limited"] is True
        assert data["hooks_fired"] == 0
        assert data["depth"] == 2
        assert data["max_depth"] == 2

    @pytest.mark.asyncio
    async def test_fire_default_max_depth(self, hooks_yaml: Path):
        """Default max_depth is 3 when not configured."""
        save(HookRegistry(), hooks_yaml)
        with patch("server.lib.storage._HOOKS_FILE", hooks_yaml):
            result = await hooks_fire("trigger_a", depth=3)
        data = json.loads(result)
        assert data["depth_limited"] is True
        assert data["max_depth"] == 3

    @pytest.mark.asyncio
    async def test_fire_invalid_source_result_json(self, hooks_yaml: Path):
        save(HookRegistry(), hooks_yaml)
        with patch("server.lib.storage._HOOKS_FILE", hooks_yaml):
            result = await hooks_fire("trigger_a", source_result="not-json")
        assert "Error" in result
        assert "not valid JSON" in result

    @pytest.mark.asyncio
    async def test_fire_non_dict_source_result(self, hooks_yaml: Path):
        save(HookRegistry(), hooks_yaml)
        with patch("server.lib.storage._HOOKS_FILE", hooks_yaml):
            result = await hooks_fire("trigger_a", source_result="[1, 2]")
        assert "Error" in result
        assert "must be a JSON object" in result

    @pytest.mark.asyncio
    async def test_fire_multiple_hooks_mixed(self, hooks_yaml: Path):
        """Mix of blocking and non-blocking hooks fires correctly."""
        reg = _make_registry([
            _hook("hook-001", "trigger_a", "target_b", blocking=False),
            _hook("hook-002", "trigger_a", "target_c", blocking=True),
        ])
        save(reg, hooks_yaml)
        mock_result = FireResult(hook_id="hook-002", status_code=200, body="ok")

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.tools.fire._fire_background") as mock_bg,
            patch("server.tools.fire._fire_single", new_callable=AsyncMock, return_value=mock_result),
        ):
            result = await hooks_fire("trigger_a")

        data = json.loads(result)
        assert data["hooks_fired"] == 2
        mock_bg.assert_called_once()

    @pytest.mark.asyncio
    async def test_fire_resolves_param_mapping(self, hooks_yaml: Path):
        """param_mapping templates are resolved against source_result."""
        reg = _make_registry([
            _hook(
                "hook-001",
                "trigger_a",
                "target_b",
                blocking=True,
                param_mapping={"path": "${result.path}"},
            ),
        ])
        save(reg, hooks_yaml)

        captured_params = {}

        async def mock_post_hook(*, hook_id, url, target_tool, params):
            captured_params.update(params)
            return FireResult(hook_id=hook_id, status_code=200, body="ok")

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.tools.fire.post_hook", side_effect=mock_post_hook),
        ):
            source = json.dumps({"result": {"path": "/tmp/project"}})
            result = await hooks_fire("trigger_a", source_result=source)

        data = json.loads(result)
        assert data["hooks_fired"] == 1
        assert captured_params["path"] == "/tmp/project"


# ── Verification response parsing ────────────────────────────────────────────


class TestParseVerificationResponse:
    def test_pass_response(self):
        raw = json.dumps({"status": "pass", "details": "all good"})
        status, details = _parse_verification_response(raw)
        assert status == "pass"
        assert details == "all good"

    def test_fail_response(self):
        raw = json.dumps({"status": "fail", "details": "task still open"})
        status, details = _parse_verification_response(raw)
        assert status == "fail"
        assert details == "task still open"

    def test_missing_status_field(self):
        """Malformed response without status field → fail."""
        raw = json.dumps({"result": "ok", "details": "something"})
        status, details = _parse_verification_response(raw)
        assert status == "fail"
        assert raw in details  # raw response preserved as details

    def test_none_result(self):
        status, details = _parse_verification_response(None)
        assert status == "fail"
        assert details == "no response"

    def test_non_json_string(self):
        status, details = _parse_verification_response("not json at all")
        assert status == "fail"
        assert "not json at all" in details

    def test_missing_details_field(self):
        raw = json.dumps({"status": "pass"})
        status, details = _parse_verification_response(raw)
        assert status == "pass"
        assert details == ""


# ── Phase 2 verification firing ──────────────────────────────────────────────


class TestVerificationFiring:
    @pytest.mark.asyncio
    async def test_phase2_fires_after_phase1(
        self, hooks_yaml: Path, verifications_yaml: Path,
    ):
        """Verification hooks fire after primary hooks, with enriched source."""
        reg = _make_registry([
            _hook("primary-001", "trigger_a", "target_b", blocking=True),
            _hook("verify-001", "trigger_a", "verify_target", verification=True),
        ])
        save(reg, hooks_yaml)

        call_order: list[str] = []

        async def mock_fire_single(hook, source):
            call_order.append(hook.id)
            if hook.id == "primary-001":
                return FireResult(
                    hook_id="primary-001", status_code=200, body="ok",
                    result="primary_done",
                )
            # Verification hook — return convention-based pass response
            return FireResult(
                hook_id="verify-001", status_code=200, body="ok",
                result=json.dumps({"status": "pass", "details": "verified"}),
            )

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.storage._VERIFICATIONS_FILE", verifications_yaml),
            patch("server.tools.fire._fire_single", side_effect=mock_fire_single),
        ):
            result = await hooks_fire("trigger_a")

        data = json.loads(result)
        # Primary fired first, then verification
        assert call_order == ["primary-001", "verify-001"]
        assert data["hooks_fired"] == 1  # Only primary counted
        assert data["results"] == [{"hook_id": "primary-001", "result": "primary_done"}]
        assert len(data["verification"]) == 1
        assert data["verification"][0]["hook_id"] == "verify-001"
        assert data["verification"][0]["status"] == "pass"
        assert data["verification"][0]["details"] == "verified"

    @pytest.mark.asyncio
    async def test_verification_receives_aggregated_results(
        self, hooks_yaml: Path, verifications_yaml: Path,
    ):
        """Verification hooks receive Phase 1 blocking results in hook_results."""
        reg = _make_registry([
            _hook("primary-001", "trigger_a", "target_b", blocking=True),
            _hook("primary-002", "trigger_a", "target_c", blocking=True),
            _hook("verify-001", "trigger_a", "verify_target", verification=True),
        ])
        save(reg, hooks_yaml)

        captured_source: dict = {}

        async def mock_fire_single(hook, source):
            if hook.verification:
                captured_source.update(source)
                return FireResult(
                    hook_id=hook.id, status_code=200, body="ok",
                    result=json.dumps({"status": "pass", "details": "ok"}),
                )
            return FireResult(
                hook_id=hook.id, status_code=200, body="ok",
                result=f"result_{hook.id}",
            )

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.storage._VERIFICATIONS_FILE", verifications_yaml),
            patch("server.tools.fire._fire_single", side_effect=mock_fire_single),
        ):
            result = await hooks_fire(
                "trigger_a", source_result='{"key": "val"}',
            )

        # Verification hook should have received hook_results from Phase 1
        assert "hook_results" in captured_source
        assert captured_source["hook_results"]["primary-001"] == "result_primary-001"
        assert captured_source["hook_results"]["primary-002"] == "result_primary-002"
        # Original source_result fields preserved
        assert captured_source["key"] == "val"

    @pytest.mark.asyncio
    async def test_verification_fail_response(
        self, hooks_yaml: Path, verifications_yaml: Path,
    ):
        """Verification hook returning fail status is recorded correctly."""
        reg = _make_registry([
            _hook("verify-001", "trigger_a", "verify_target", verification=True),
        ])
        save(reg, hooks_yaml)

        async def mock_fire_single(hook, source):
            return FireResult(
                hook_id=hook.id, status_code=200, body="ok",
                result=json.dumps({"status": "fail", "details": "task still open"}),
            )

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.storage._VERIFICATIONS_FILE", verifications_yaml),
            patch("server.tools.fire._fire_single", side_effect=mock_fire_single),
        ):
            result = await hooks_fire("trigger_a")

        data = json.loads(result)
        assert data["verification"][0]["status"] == "fail"
        assert data["verification"][0]["details"] == "task still open"

    @pytest.mark.asyncio
    async def test_verification_malformed_response(
        self, hooks_yaml: Path, verifications_yaml: Path,
    ):
        """Malformed verification response (missing status) → fail."""
        reg = _make_registry([
            _hook("verify-001", "trigger_a", "verify_target", verification=True),
        ])
        save(reg, hooks_yaml)

        async def mock_fire_single(hook, source):
            return FireResult(
                hook_id=hook.id, status_code=200, body="ok",
                result=json.dumps({"result": "ok"}),  # Missing 'status' field
            )

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.storage._VERIFICATIONS_FILE", verifications_yaml),
            patch("server.tools.fire._fire_single", side_effect=mock_fire_single),
        ):
            result = await hooks_fire("trigger_a")

        data = json.loads(result)
        assert data["verification"][0]["status"] == "fail"

    @pytest.mark.asyncio
    async def test_verification_http_error_treated_as_fail(
        self, hooks_yaml: Path, failures_yaml: Path, verifications_yaml: Path,
    ):
        """HTTP error on verification hook → fail with error details."""
        reg = _make_registry([
            _hook("verify-001", "trigger_a", "verify_target", verification=True),
        ])
        save(reg, hooks_yaml)

        async def mock_fire_single(hook, source):
            return FireResult(
                hook_id=hook.id, status_code=500,
                body="Internal Server Error",
                error="HTTP 500",
            )

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.storage._FAILURES_FILE", failures_yaml),
            patch("server.lib.storage._VERIFICATIONS_FILE", verifications_yaml),
            patch("server.tools.fire._fire_single", side_effect=mock_fire_single),
        ):
            result = await hooks_fire("trigger_a")

        data = json.loads(result)
        assert data["verification"][0]["status"] == "fail"
        assert "HTTP 500" in data["verification"][0]["details"]

    @pytest.mark.asyncio
    async def test_verification_exception_treated_as_fail(
        self, hooks_yaml: Path, failures_yaml: Path, verifications_yaml: Path,
    ):
        """Exception in verification hook → fail."""
        reg = _make_registry([
            _hook("verify-001", "trigger_a", "verify_target", verification=True),
        ])
        save(reg, hooks_yaml)

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.storage._FAILURES_FILE", failures_yaml),
            patch("server.lib.storage._VERIFICATIONS_FILE", verifications_yaml),
            patch(
                "server.tools.fire._fire_single",
                new_callable=AsyncMock,
                side_effect=ConnectionError("refused"),
            ),
        ):
            result = await hooks_fire("trigger_a")

        data = json.loads(result)
        assert data["verification"][0]["status"] == "fail"
        assert "Exception" in data["verification"][0]["details"]

    @pytest.mark.asyncio
    async def test_no_verification_hooks_no_phase2(self, hooks_yaml: Path):
        """When no verification hooks exist, no Phase 2 and no verification key."""
        reg = _make_registry([
            _hook("hook-001", "trigger_a", "target_b", blocking=True),
        ])
        save(reg, hooks_yaml)
        mock_result = FireResult(hook_id="hook-001", status_code=200, body="ok")

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.tools.fire._fire_single", new_callable=AsyncMock, return_value=mock_result),
        ):
            result = await hooks_fire("trigger_a")

        data = json.loads(result)
        assert "verification" not in data

    @pytest.mark.asyncio
    async def test_verification_results_stored(
        self, hooks_yaml: Path, verifications_yaml: Path,
    ):
        """Verification results are persisted via store_verification_result."""
        reg = _make_registry([
            _hook("verify-001", "trigger_a", "verify_target", verification=True),
        ])
        save(reg, hooks_yaml)

        async def mock_fire_single(hook, source):
            return FireResult(
                hook_id=hook.id, status_code=200, body="ok",
                result=json.dumps({"status": "pass", "details": "confirmed"}),
            )

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.storage._VERIFICATIONS_FILE", verifications_yaml),
            patch("server.tools.fire._fire_single", side_effect=mock_fire_single),
        ):
            await hooks_fire("trigger_a")

        # Check the verifications file was written
        from server.lib.storage import load_verification_results
        with patch("server.lib.storage._VERIFICATIONS_FILE", verifications_yaml):
            entries = load_verification_results()
        assert len(entries) == 1
        assert entries[0]["hook_id"] == "verify-001"
        assert entries[0]["status"] == "pass"
        assert entries[0]["details"] == "confirmed"
        assert entries[0]["trigger_tool"] == "trigger_a"


# ── Condition merge with source_result ───────────────────────────────────────────


class TestConditionMerge:
    """Tests for source_result → condition merge behavior in hooks_fire."""

    @pytest.mark.asyncio
    async def test_todo_condition_fires_with_task_id(self, hooks_yaml: Path, proj_yaml: Path):
        """Hook with condition 'todo.todoist_task_id' fires when source_result contains it."""
        reg = _make_registry([
            _hook("hook-001", "trigger_a", "target_b", condition="todo.todoist_task_id"),
        ])
        save(reg, hooks_yaml)
        proj_yaml.write_text("")  # Empty base config

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.conditions._PROJ_CONFIG_PATH", proj_yaml),
            patch("server.tools.fire._fire_background") as mock_bg,
        ):
            # source_result contains todoist_task_id
            source = json.dumps({"todoist_task_id": "abc123"})
            result = await hooks_fire("trigger_a", source_result=source)

        data = json.loads(result)
        assert data["hooks_fired"] == 1
        assert data["skipped"] == 0
        mock_bg.assert_called_once()

    @pytest.mark.asyncio
    async def test_todo_condition_skips_without_task_id(self, hooks_yaml: Path, proj_yaml: Path):
        """Hook with condition 'todo.todoist_task_id' skips when source_result lacks it."""
        reg = _make_registry([
            _hook("hook-001", "trigger_a", "target_b", condition="todo.todoist_task_id"),
        ])
        save(reg, hooks_yaml)
        proj_yaml.write_text("")  # Empty base config

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.conditions._PROJ_CONFIG_PATH", proj_yaml),
        ):
            # source_result does NOT contain todoist_task_id
            source = json.dumps({"other_field": "value"})
            result = await hooks_fire("trigger_a", source_result=source)

        data = json.loads(result)
        assert data["hooks_fired"] == 0
        assert data["skipped"] == 1

    @pytest.mark.asyncio
    async def test_project_condition_fires_with_project_id(self, hooks_yaml: Path, proj_yaml: Path):
        """Hook with condition 'project.todoist_project_id' fires when source_result contains it."""
        reg = _make_registry([
            _hook("hook-001", "trigger_a", "target_b", condition="project.todoist_project_id"),
        ])
        save(reg, hooks_yaml)
        proj_yaml.write_text("")  # Empty base config

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.conditions._PROJ_CONFIG_PATH", proj_yaml),
            patch("server.tools.fire._fire_background") as mock_bg,
        ):
            source = json.dumps({"todoist_project_id": "proj456"})
            result = await hooks_fire("trigger_a", source_result=source)

        data = json.loads(result)
        assert data["hooks_fired"] == 1
        assert data["skipped"] == 0
        mock_bg.assert_called_once()

    @pytest.mark.asyncio
    async def test_project_condition_skips_without_project_id(self, hooks_yaml: Path, proj_yaml: Path):
        """Hook with condition 'project.todoist_project_id' skips when source_result lacks it."""
        reg = _make_registry([
            _hook("hook-001", "trigger_a", "target_b", condition="project.todoist_project_id"),
        ])
        save(reg, hooks_yaml)
        proj_yaml.write_text("")

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.conditions._PROJ_CONFIG_PATH", proj_yaml),
        ):
            source = json.dumps({"other": "value"})
            result = await hooks_fire("trigger_a", source_result=source)

        data = json.loads(result)
        assert data["hooks_fired"] == 0
        assert data["skipped"] == 1

    @pytest.mark.asyncio
    async def test_compound_condition_with_mixed_config(self, hooks_yaml: Path, proj_yaml: Path):
        """Compound condition evaluates using both base config and source_result."""
        reg = _make_registry([
            _hook(
                "hook-001",
                "trigger_a",
                "target_b",
                condition="todoist.enabled and project.todoist_project_id",
            ),
        ])
        save(reg, hooks_yaml)
        # Base config has todoist.enabled=True
        proj_yaml.write_text(yaml.dump({"todoist": {"enabled": True}}))

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.conditions._PROJ_CONFIG_PATH", proj_yaml),
            patch("server.tools.fire._fire_background") as mock_bg,
        ):
            # source_result provides the project_id
            source = json.dumps({"todoist_project_id": "proj789"})
            result = await hooks_fire("trigger_a", source_result=source)

        data = json.loads(result)
        assert data["hooks_fired"] == 1
        assert data["skipped"] == 0
        mock_bg.assert_called_once()

    @pytest.mark.asyncio
    async def test_trello_card_id_merges_to_project(self, hooks_yaml: Path, proj_yaml: Path):
        """trello_card_id from source_result merges into 'project' section."""
        reg = _make_registry([
            _hook("hook-001", "trigger_a", "target_b", condition="project.trello_card_id"),
        ])
        save(reg, hooks_yaml)
        proj_yaml.write_text("")

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.conditions._PROJ_CONFIG_PATH", proj_yaml),
            patch("server.tools.fire._fire_background") as mock_bg,
        ):
            source = json.dumps({"trello_card_id": "cardABC"})
            result = await hooks_fire("trigger_a", source_result=source)

        data = json.loads(result)
        assert data["hooks_fired"] == 1
        mock_bg.assert_called_once()

    @pytest.mark.asyncio
    async def test_trello_checklist_id_merges_to_both(self, hooks_yaml: Path, proj_yaml: Path):
        """trello_checklist_id merges into both 'todo' and 'project' sections."""
        reg = _make_registry([
            _hook(
                "hook-001",
                "trigger_a",
                "target_b",
                condition="project.trello_checklist_id and todo.trello_checklist_id",
            ),
        ])
        save(reg, hooks_yaml)
        proj_yaml.write_text("")

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.conditions._PROJ_CONFIG_PATH", proj_yaml),
            patch("server.tools.fire._fire_background") as mock_bg,
        ):
            source = json.dumps({"trello_checklist_id": "check123"})
            result = await hooks_fire("trigger_a", source_result=source)

        data = json.loads(result)
        assert data["hooks_fired"] == 1
        mock_bg.assert_called_once()

    @pytest.mark.asyncio
    async def test_jira_issue_key_merges_to_todo(self, hooks_yaml: Path, proj_yaml: Path):
        """jira_issue_key from source_result merges into 'todo' section."""
        reg = _make_registry([
            _hook("hook-001", "trigger_a", "target_b", condition="todo.jira_issue_key"),
        ])
        save(reg, hooks_yaml)
        proj_yaml.write_text("")

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.conditions._PROJ_CONFIG_PATH", proj_yaml),
            patch("server.tools.fire._fire_background") as mock_bg,
        ):
            source = json.dumps({"jira_issue_key": "PROJ-123"})
            result = await hooks_fire("trigger_a", source_result=source)

        data = json.loads(result)
        assert data["hooks_fired"] == 1
        mock_bg.assert_called_once()

    @pytest.mark.asyncio
    async def test_base_config_overrides_source_result(self, hooks_yaml: Path, proj_yaml: Path):
        """Base config values take precedence over source_result merge."""
        reg = _make_registry([
            _hook("hook-001", "trigger_a", "target_b", condition="todo.todoist_task_id"),
        ])
        save(reg, hooks_yaml)
        # Base config has the field
        proj_yaml.write_text(yaml.dump({"todo": {"todoist_task_id": "base_value"}}))

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.conditions._PROJ_CONFIG_PATH", proj_yaml),
            patch("server.tools.fire._fire_background") as mock_bg,
        ):
            # source_result also has it, but base config wins
            source = json.dumps({"todoist_task_id": "source_value"})
            result = await hooks_fire("trigger_a", source_result=source)

        data = json.loads(result)
        # Should fire because base config has it
        assert data["hooks_fired"] == 1
        mock_bg.assert_called_once()
