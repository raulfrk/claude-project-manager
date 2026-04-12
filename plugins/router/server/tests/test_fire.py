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
from server.tools.fire import (
    _parse_verification_response,
    _resolve_server_url,
    hooks_fire,
)

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


# ── _resolve_server_url tests ─────────────────────────────────────────────────


class TestResolveServerUrl:
    def test_unix_mode_reads_registry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """In Unix mode, reads the socket path from the registry file."""
        registry_file = tmp_path / "trello"
        registry_file.write_text("/tmp/claude-cpm-trello-99999.sock")
        monkeypatch.setenv("HOOK_TRANSPORT", "unix")
        monkeypatch.setattr("server.tools.fire._SOCKET_REGISTRY_DIR", tmp_path)
        with patch("server.tools.fire.os.path.exists", return_value=True):
            result = _resolve_server_url("trello", 19100)
        assert result == "unix:///tmp/claude-cpm-trello-99999.sock"

    def test_unix_mode_stale_registry_falls_back_to_glob(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Stale registry (socket doesn't exist) falls back to glob."""
        registry_file = tmp_path / "trello"
        registry_file.write_text("/tmp/claude-cpm-trello-10.sock")  # sandbox PID
        monkeypatch.setenv("HOOK_TRANSPORT", "unix")
        monkeypatch.setattr("server.tools.fire._SOCKET_REGISTRY_DIR", tmp_path)
        with (
            patch("server.tools.fire.os.path.exists", return_value=False),
            patch(
                "server.tools.fire.glob.glob",
                return_value=[
                    "/tmp/claude-cpm-trello-99999.sock",
                ],
            ),
            patch("server.tools.fire.os.path.getmtime", return_value=1000),
        ):
            result = _resolve_server_url("trello", 19100)
        assert result == "unix:///tmp/claude-cpm-trello-99999.sock"

    def test_unix_mode_falls_back_to_name_when_no_sockets(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Falls back to server name when registry missing AND no glob matches."""
        monkeypatch.setenv("HOOK_TRANSPORT", "unix")
        monkeypatch.setattr("server.tools.fire._SOCKET_REGISTRY_DIR", tmp_path)
        with patch("server.tools.fire.glob.glob", return_value=[]):
            result = _resolve_server_url("trello", 19100)
        assert result == "trello"

    def test_tcp_mode_uses_port_mapping(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """In TCP mode, uses the default port for the server."""
        monkeypatch.setenv("HOOK_TRANSPORT", "tcp")
        result = _resolve_server_url("trello", 19100)
        assert result == "http://127.0.0.1:19104/hook"

    def test_tcp_mode_fallback_port(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """In TCP mode, unknown servers use the hooks_port fallback."""
        monkeypatch.setenv("HOOK_TRANSPORT", "tcp")
        result = _resolve_server_url("unknown-plugin", 19100)
        assert result == "http://127.0.0.1:19100/hook"

    def test_default_is_unix_mode(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Default mode (no HOOK_TRANSPORT env var) is Unix."""
        monkeypatch.delenv("HOOK_TRANSPORT", raising=False)
        monkeypatch.setattr("server.tools.fire._SOCKET_REGISTRY_DIR", tmp_path)
        with patch("server.tools.fire.glob.glob", return_value=[]):
            result = _resolve_server_url("proj", 19100)
        assert result == "proj"  # falls back to server name


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
    async def test_fire_nonblocking_hook_dispatched(self, hooks_yaml: Path):
        """Non-blocking hook is dispatched as a background task."""
        reg = _make_registry(
            [
                _hook("hook-001", "trigger_a", "target_b", blocking=False),
            ]
        )
        save(reg, hooks_yaml)
        mock_result = FireResult(hook_id="hook-001", status_code=200, body="ok")

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch(
                "server.tools.fire._fire_single", new_callable=AsyncMock, return_value=mock_result
            ),
        ):
            result = await hooks_fire("trigger_a", source_result='{"key": "val"}')

        data = json.loads(result)
        assert data["hooks_fired"] == 0
        assert data["non_blocking_dispatched"] == 1
        assert data["skipped"] == 0
        assert len(data["results"]) == 1
        assert data["results"][0]["hook_id"] == "hook-001"
        assert data["results"][0]["status"] == "dispatched"

    @pytest.mark.asyncio
    async def test_fire_blocking_hook_success(self, hooks_yaml: Path):
        """Blocking hook awaited; successful result reported."""
        reg = _make_registry(
            [
                _hook("hook-001", "trigger_a", "target_b", blocking=True),
            ]
        )
        save(reg, hooks_yaml)
        mock_result = FireResult(hook_id="hook-001", status_code=200, body="ok")

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch(
                "server.tools.fire._fire_single", new_callable=AsyncMock, return_value=mock_result
            ),
        ):
            result = await hooks_fire("trigger_a")

        data = json.loads(result)
        assert data["hooks_fired"] == 1
        assert data["errors"] == []
        assert data["results"] == [
            {"hook_id": "hook-001", "result": None, "target_tool": "target_b"}
        ]

    @pytest.mark.asyncio
    async def test_fire_blocking_hook_success_with_result(self, hooks_yaml: Path):
        """Blocking hook with result field passes it through in summary."""
        reg = _make_registry(
            [
                _hook("hook-001", "trigger_a", "target_b", blocking=True),
            ]
        )
        save(reg, hooks_yaml)
        mock_result = FireResult(hook_id="hook-001", status_code=200, body="ok", result="created")

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch(
                "server.tools.fire._fire_single", new_callable=AsyncMock, return_value=mock_result
            ),
        ):
            result = await hooks_fire("trigger_a")

        data = json.loads(result)
        assert data["hooks_fired"] == 1
        assert data["errors"] == []
        assert data["results"] == [
            {"hook_id": "hook-001", "result": "created", "target_tool": "target_b"}
        ]

    @pytest.mark.asyncio
    async def test_fire_blocking_hook_http_error(self, hooks_yaml: Path, failures_yaml: Path):
        """Blocking hook that fails logs failure and reports error."""
        reg = _make_registry(
            [
                _hook("hook-001", "trigger_a", "target_b", blocking=True),
            ]
        )
        save(reg, hooks_yaml)
        mock_result = FireResult(hook_id="hook-001", status_code=500, body="Internal Server Error")

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.storage._FAILURES_FILE", failures_yaml),
            patch(
                "server.tools.fire._fire_single", new_callable=AsyncMock, return_value=mock_result
            ),
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
        reg = _make_registry(
            [
                _hook("hook-001", "trigger_a", "target_b", blocking=True),
            ]
        )
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
        reg = _make_registry(
            [
                _hook("hook-001", "trigger_a", "target_b", condition="feature.enabled"),
            ]
        )
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
    async def test_fire_inactive_condition_skips_hook_e2e(self, hooks_yaml: Path, proj_yaml: Path):
        """E2E: hook with inactive condition (sync.todoist.enabled: false) is skipped entirely.

        Verifies:
        1. Target tool is never called (_fire_single not invoked)
        2. Hook is absent from results
        3. skipped count reflects the inactive hook
        """
        reg = _make_registry(
            [
                _hook(
                    "hook-todoist",
                    "todo_complete",
                    "todoist_complete_task_hook",
                    server="todoist",
                    blocking=True,
                    condition="sync.todoist.enabled",
                ),
            ]
        )
        save(reg, hooks_yaml)
        # Explicitly set the condition to false (not missing — actively disabled)
        proj_yaml.write_text(yaml.dump({"sync": {"todoist": {"enabled": False}}}))

        mock_fire_single = AsyncMock()

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.conditions._PROJ_CONFIG_PATH", proj_yaml),
            patch("server.tools.fire._fire_single", mock_fire_single),
        ):
            result = await hooks_fire("todo_complete", source_result='{"todo_id": "123"}')

        data = json.loads(result)
        # Hook must not have been executed
        mock_fire_single.assert_not_called()
        assert data["hooks_fired"] == 0
        assert data["skipped"] == 1
        assert data["results"] == []
        assert data["errors"] == []

    @pytest.mark.asyncio
    async def test_fire_resolves_param_mapping(self, hooks_yaml: Path):
        """param_mapping templates are resolved against source_result."""
        reg = _make_registry(
            [
                _hook(
                    "hook-001",
                    "trigger_a",
                    "target_b",
                    blocking=True,
                    param_mapping={"path": "${result.path}"},
                ),
            ]
        )
        save(reg, hooks_yaml)

        captured_params = {}

        async def mock_post_hook(*, hook_id, url, target_tool, params):
            captured_params.update(params)
            return FireResult(hook_id=hook_id, status_code=200, body="ok")

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.tools.fire.post_hook", side_effect=mock_post_hook),
            patch("server.tools.fire._resolve_server_url", return_value="unix:///tmp/test.sock"),
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
        self,
        hooks_yaml: Path,
        verifications_yaml: Path,
    ):
        """Verification hooks fire after primary hooks, with enriched source."""
        reg = _make_registry(
            [
                _hook("primary-001", "trigger_a", "target_b", blocking=True),
                _hook("verify-001", "trigger_a", "verify_target", verification=True),
            ]
        )
        save(reg, hooks_yaml)

        call_order: list[str] = []

        async def mock_fire_single(hook, source):
            call_order.append(hook.id)
            if hook.id == "primary-001":
                return FireResult(
                    hook_id="primary-001",
                    status_code=200,
                    body="ok",
                    result="primary_done",
                )
            # Verification hook — return convention-based pass response
            return FireResult(
                hook_id="verify-001",
                status_code=200,
                body="ok",
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
        assert data["results"] == [
            {"hook_id": "primary-001", "result": "primary_done", "target_tool": "target_b"}
        ]
        assert len(data["verification"]) == 1
        assert data["verification"][0]["hook_id"] == "verify-001"
        assert data["verification"][0]["status"] == "pass"
        assert data["verification"][0]["details"] == "verified"

    @pytest.mark.asyncio
    async def test_verification_receives_aggregated_results(
        self,
        hooks_yaml: Path,
        verifications_yaml: Path,
    ):
        """Verification hooks receive Phase 1 blocking results in hook_results."""
        reg = _make_registry(
            [
                _hook("primary-001", "trigger_a", "target_b", blocking=True),
                _hook("primary-002", "trigger_a", "target_c", blocking=True),
                _hook("verify-001", "trigger_a", "verify_target", verification=True),
            ]
        )
        save(reg, hooks_yaml)

        captured_source: dict = {}

        async def mock_fire_single(hook, source):
            if hook.verification:
                captured_source.update(source)
                return FireResult(
                    hook_id=hook.id,
                    status_code=200,
                    body="ok",
                    result=json.dumps({"status": "pass", "details": "ok"}),
                )
            return FireResult(
                hook_id=hook.id,
                status_code=200,
                body="ok",
                result=f"result_{hook.id}",
            )

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.storage._VERIFICATIONS_FILE", verifications_yaml),
            patch("server.tools.fire._fire_single", side_effect=mock_fire_single),
        ):
            await hooks_fire(
                "trigger_a",
                source_result='{"key": "val"}',
            )

        # Verification hook should have received hook_results from Phase 1
        assert "hook_results" in captured_source
        assert captured_source["hook_results"]["primary-001"] == "result_primary-001"
        assert captured_source["hook_results"]["primary-002"] == "result_primary-002"
        # Original source_result fields preserved
        assert captured_source["key"] == "val"

    @pytest.mark.asyncio
    async def test_verification_fail_response(
        self,
        hooks_yaml: Path,
        verifications_yaml: Path,
    ):
        """Verification hook returning fail status is recorded correctly."""
        reg = _make_registry(
            [
                _hook("verify-001", "trigger_a", "verify_target", verification=True),
            ]
        )
        save(reg, hooks_yaml)

        async def mock_fire_single(hook, source):
            return FireResult(
                hook_id=hook.id,
                status_code=200,
                body="ok",
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
        self,
        hooks_yaml: Path,
        verifications_yaml: Path,
    ):
        """Malformed verification response (missing status) → fail."""
        reg = _make_registry(
            [
                _hook("verify-001", "trigger_a", "verify_target", verification=True),
            ]
        )
        save(reg, hooks_yaml)

        async def mock_fire_single(hook, source):
            return FireResult(
                hook_id=hook.id,
                status_code=200,
                body="ok",
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
        self,
        hooks_yaml: Path,
        failures_yaml: Path,
        verifications_yaml: Path,
    ):
        """HTTP error on verification hook → fail with error details."""
        reg = _make_registry(
            [
                _hook("verify-001", "trigger_a", "verify_target", verification=True),
            ]
        )
        save(reg, hooks_yaml)

        async def mock_fire_single(hook, source):
            return FireResult(
                hook_id=hook.id,
                status_code=500,
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
        self,
        hooks_yaml: Path,
        failures_yaml: Path,
        verifications_yaml: Path,
    ):
        """Exception in verification hook → fail."""
        reg = _make_registry(
            [
                _hook("verify-001", "trigger_a", "verify_target", verification=True),
            ]
        )
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
        reg = _make_registry(
            [
                _hook("hook-001", "trigger_a", "target_b", blocking=True),
            ]
        )
        save(reg, hooks_yaml)
        mock_result = FireResult(hook_id="hook-001", status_code=200, body="ok")

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch(
                "server.tools.fire._fire_single", new_callable=AsyncMock, return_value=mock_result
            ),
        ):
            result = await hooks_fire("trigger_a")

        data = json.loads(result)
        assert "verification" not in data

    @pytest.mark.asyncio
    async def test_verification_results_stored(
        self,
        hooks_yaml: Path,
        verifications_yaml: Path,
    ):
        """Verification results are persisted via store_verification_result."""
        reg = _make_registry(
            [
                _hook("verify-001", "trigger_a", "verify_target", verification=True),
            ]
        )
        save(reg, hooks_yaml)

        async def mock_fire_single(hook, source):
            return FireResult(
                hook_id=hook.id,
                status_code=200,
                body="ok",
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
        reg = _make_registry(
            [
                _hook("hook-001", "trigger_a", "target_b", condition="todo.todoist_task_id"),
            ]
        )
        save(reg, hooks_yaml)
        proj_yaml.write_text("")  # Empty base config

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.conditions._PROJ_CONFIG_PATH", proj_yaml),
            patch(
                "server.tools.fire._fire_single",
                new_callable=AsyncMock,
                return_value=FireResult(hook_id="hook-001", status_code=200, body="ok"),
            ),
        ):
            # source_result contains todoist_task_id
            source = json.dumps({"todoist_task_id": "abc123"})
            result = await hooks_fire("trigger_a", source_result=source)

        data = json.loads(result)
        # Default blocking=False, so hook is dispatched as non-blocking
        assert data["non_blocking_dispatched"] == 1
        assert data["skipped"] == 0

    @pytest.mark.asyncio
    async def test_todo_condition_skips_without_task_id(self, hooks_yaml: Path, proj_yaml: Path):
        """Hook with condition 'todo.todoist_task_id' skips when source_result lacks it."""
        reg = _make_registry(
            [
                _hook("hook-001", "trigger_a", "target_b", condition="todo.todoist_task_id"),
            ]
        )
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
        reg = _make_registry(
            [
                _hook("hook-001", "trigger_a", "target_b", condition="project.todoist_project_id"),
            ]
        )
        save(reg, hooks_yaml)
        proj_yaml.write_text("")  # Empty base config

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.conditions._PROJ_CONFIG_PATH", proj_yaml),
            patch(
                "server.tools.fire._fire_single",
                new_callable=AsyncMock,
                return_value=FireResult(hook_id="hook-001", status_code=200, body="ok"),
            ),
        ):
            source = json.dumps({"todoist_project_id": "proj456"})
            result = await hooks_fire("trigger_a", source_result=source)

        data = json.loads(result)
        assert data["non_blocking_dispatched"] == 1
        assert data["skipped"] == 0

    @pytest.mark.asyncio
    async def test_project_condition_skips_without_project_id(
        self, hooks_yaml: Path, proj_yaml: Path
    ):
        """Hook with condition 'project.todoist_project_id' skips when source_result lacks it."""
        reg = _make_registry(
            [
                _hook("hook-001", "trigger_a", "target_b", condition="project.todoist_project_id"),
            ]
        )
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
        reg = _make_registry(
            [
                _hook(
                    "hook-001",
                    "trigger_a",
                    "target_b",
                    condition="sync.todoist.enabled and project.todoist_project_id",
                ),
            ]
        )
        save(reg, hooks_yaml)
        # Base config has sync.todoist.enabled=True
        proj_yaml.write_text(yaml.dump({"sync": {"todoist": {"enabled": True}}}))

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.conditions._PROJ_CONFIG_PATH", proj_yaml),
            patch(
                "server.tools.fire._fire_single",
                new_callable=AsyncMock,
                return_value=FireResult(hook_id="hook-001", status_code=200, body="ok"),
            ),
        ):
            # source_result provides the project_id
            source = json.dumps({"todoist_project_id": "proj789"})
            result = await hooks_fire("trigger_a", source_result=source)

        data = json.loads(result)
        assert data["non_blocking_dispatched"] == 1
        assert data["skipped"] == 0

    @pytest.mark.asyncio
    async def test_trello_card_id_merges_to_project(self, hooks_yaml: Path, proj_yaml: Path):
        """trello_card_id from source_result merges into 'project' section."""
        reg = _make_registry(
            [
                _hook("hook-001", "trigger_a", "target_b", condition="project.trello_card_id"),
            ]
        )
        save(reg, hooks_yaml)
        proj_yaml.write_text("")

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.conditions._PROJ_CONFIG_PATH", proj_yaml),
            patch(
                "server.tools.fire._fire_single",
                new_callable=AsyncMock,
                return_value=FireResult(hook_id="hook-001", status_code=200, body="ok"),
            ),
        ):
            source = json.dumps({"trello_card_id": "cardABC"})
            result = await hooks_fire("trigger_a", source_result=source)

        data = json.loads(result)
        assert data["non_blocking_dispatched"] == 1

    @pytest.mark.asyncio
    async def test_trello_checklist_id_merges_to_both(self, hooks_yaml: Path, proj_yaml: Path):
        """trello_checklist_id merges into both 'todo' and 'project' sections."""
        reg = _make_registry(
            [
                _hook(
                    "hook-001",
                    "trigger_a",
                    "target_b",
                    condition="project.trello_checklist_id and todo.trello_checklist_id",
                ),
            ]
        )
        save(reg, hooks_yaml)
        proj_yaml.write_text("")

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.conditions._PROJ_CONFIG_PATH", proj_yaml),
            patch(
                "server.tools.fire._fire_single",
                new_callable=AsyncMock,
                return_value=FireResult(hook_id="hook-001", status_code=200, body="ok"),
            ),
        ):
            source = json.dumps({"trello_checklist_id": "check123"})
            result = await hooks_fire("trigger_a", source_result=source)

        data = json.loads(result)
        assert data["non_blocking_dispatched"] == 1

    @pytest.mark.asyncio
    async def test_jira_issue_key_merges_to_todo(self, hooks_yaml: Path, proj_yaml: Path):
        """jira_issue_key from source_result merges into 'todo' section."""
        reg = _make_registry(
            [
                _hook("hook-001", "trigger_a", "target_b", condition="todo.jira_issue_key"),
            ]
        )
        save(reg, hooks_yaml)
        proj_yaml.write_text("")

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.conditions._PROJ_CONFIG_PATH", proj_yaml),
            patch(
                "server.tools.fire._fire_single",
                new_callable=AsyncMock,
                return_value=FireResult(hook_id="hook-001", status_code=200, body="ok"),
            ),
        ):
            source = json.dumps({"jira_issue_key": "PROJ-123"})
            result = await hooks_fire("trigger_a", source_result=source)

        data = json.loads(result)
        assert data["non_blocking_dispatched"] == 1

    @pytest.mark.asyncio
    async def test_base_config_overrides_source_result(self, hooks_yaml: Path, proj_yaml: Path):
        """Base config values take precedence over source_result merge."""
        reg = _make_registry(
            [
                _hook("hook-001", "trigger_a", "target_b", condition="todo.todoist_task_id"),
            ]
        )
        save(reg, hooks_yaml)
        # Base config has the field
        proj_yaml.write_text(yaml.dump({"todo": {"todoist_task_id": "base_value"}}))

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.conditions._PROJ_CONFIG_PATH", proj_yaml),
            patch(
                "server.tools.fire._fire_single",
                new_callable=AsyncMock,
                return_value=FireResult(hook_id="hook-001", status_code=200, body="ok"),
            ),
        ):
            # source_result also has it, but base config wins
            source = json.dumps({"todoist_task_id": "source_value"})
            result = await hooks_fire("trigger_a", source_result=source)

        data = json.loads(result)
        # Should fire because base config has it (non-blocking by default)
        assert data["non_blocking_dispatched"] == 1


class TestBlockingAll:
    """Tests for 389.1 — top_level field, feedback_mapping fix."""

    @pytest.mark.anyio
    async def test_top_level_true_at_depth_zero(
        self,
        hooks_yaml: Path,
        failures_yaml: Path,
        verifications_yaml: Path,
        proj_yaml: Path,
    ) -> None:
        """Response includes top_level=True when depth=0."""
        # Need at least one hook so we reach the summary code path (which adds top_level)
        hook_data = {
            "hooks": [
                {
                    "id": "h-tl",
                    "trigger_tool": "some_tool",
                    "target_tool": "some_target",
                    "server": "proj",
                    "blocking": True,
                    "param_mapping": {},
                }
            ]
        }
        hooks_yaml.write_text(__import__("yaml").dump(hook_data))
        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.storage._FAILURES_FILE", failures_yaml),
            patch("server.tools.fire._fire_single", new_callable=AsyncMock) as mock_fire,
        ):
            mock_fire.return_value = FireResult(hook_id="h-tl", status_code=200, body="ok")
            result_json = await hooks_fire("some_tool", source_result="{}", depth=0)
        result = __import__("json").loads(result_json)
        assert result.get("top_level") is True

    @pytest.mark.anyio
    async def test_top_level_absent_at_depth_one(
        self,
        hooks_yaml: Path,
        failures_yaml: Path,
        verifications_yaml: Path,
        proj_yaml: Path,
    ) -> None:
        """Response does NOT include top_level=True when depth > 0 (or depth limit hit)."""
        hook_data = {
            "hooks": [
                {
                    "id": "h-tl2",
                    "trigger_tool": "some_tool",
                    "target_tool": "some_target",
                    "server": "proj",
                    "blocking": True,
                    "param_mapping": {},
                }
            ]
        }
        hooks_yaml.write_text(__import__("yaml").dump(hook_data))
        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.storage._FAILURES_FILE", failures_yaml),
            patch("server.tools.fire._fire_single", new_callable=AsyncMock) as mock_fire,
        ):
            mock_fire.return_value = FireResult(hook_id="h-tl2", status_code=200, body="ok")
            result_json = await hooks_fire("some_tool", source_result="{}", depth=1)
        result = __import__("json").loads(result_json)
        assert result.get("top_level") is not True

    @pytest.mark.anyio
    async def test_feedback_mapping_correct_when_hook_fails(
        self,
        hooks_yaml: Path,
        failures_yaml: Path,
        verifications_yaml: Path,
        proj_yaml: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When hook 1 fails and hook 2 succeeds, feedback applies to hook 2's result only."""
        import yaml

        from server.lib.http_client import FireResult

        hook_data = {
            "hooks": [
                {
                    "id": "h-fail",
                    "trigger_tool": "test_trigger",
                    "target_tool": "target_fail",
                    "server": "proj",
                    "blocking": True,
                    "param_mapping": {},
                },
                {
                    "id": "h-ok",
                    "trigger_tool": "test_trigger",
                    "target_tool": "target_ok",
                    "server": "proj",
                    "blocking": True,
                    "param_mapping": {},
                    "feedback_mapping": {"todoist_task_id": "todoist_task_id"},
                    "feedback_tool": "todo_update",
                },
            ]
        }
        hooks_yaml.write_text(yaml.dump(hook_data))

        call_count = 0

        async def mock_post_hook(hook_id, url, target_tool, params):
            nonlocal call_count
            call_count += 1
            if target_tool == "target_fail":
                return FireResult(
                    hook_id=hook_id, status_code=500, body="error", error="internal error"
                )
            return FireResult(
                hook_id=hook_id,
                status_code=200,
                body='{"todoist_task_id": "t123"}',
                result='{"todoist_task_id": "t123"}',
            )

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.storage._FAILURES_FILE", failures_yaml),
            patch("server.tools.fire._resolve_server_url", return_value="unix:///tmp/test.sock"),
            patch("server.tools.fire.post_hook", side_effect=mock_post_hook),
        ):
            result_json = await hooks_fire(
                "test_trigger", source_result='{"todo_id": "1"}', depth=0
            )

        result = __import__("json").loads(result_json)
        assert result["hooks_fired"] == 2
        # h-fail should be in errors, not in results
        assert any(e.get("hook_id") == "h-fail" for e in result["errors"])
        # h-ok should be in results
        assert any(r.get("hook_id") == "h-ok" for r in result["results"])


# ── Blocking vs non-blocking dispatch ─────────────────────────────────────────


class TestBlockingVsNonBlockingDispatch:
    """Comprehensive tests for blocking vs non-blocking hook dispatch behavior."""

    @pytest.mark.asyncio
    async def test_mixed_batch_two_blocking_one_nonblocking(self, hooks_yaml: Path):
        """2 blocking + 1 non-blocking: blocking results in results, non-blocking only in count."""
        reg = _make_registry(
            [
                _hook("b1", "trigger_a", "target_1", blocking=True),
                _hook("b2", "trigger_a", "target_2", blocking=True),
                _hook("nb1", "trigger_a", "target_3", blocking=False),
            ]
        )
        save(reg, hooks_yaml)

        async def mock_fire(hook, source):
            return FireResult(hook_id=hook.id, status_code=200, body="ok", result=f"res_{hook.id}")

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.tools.fire._fire_single", side_effect=mock_fire),
        ):
            result = await hooks_fire("trigger_a")

        data = json.loads(result)
        assert data["hooks_fired"] == 2
        assert data["non_blocking_dispatched"] == 1
        assert data["skipped"] == 0
        assert len(data["results"]) == 3
        blocking_results = [r for r in data["results"] if r.get("status") != "dispatched"]
        dispatched_results = [r for r in data["results"] if r.get("status") == "dispatched"]
        blocking_ids = {r["hook_id"] for r in blocking_results}
        assert blocking_ids == {"b1", "b2"}
        assert len(dispatched_results) == 1
        assert dispatched_results[0]["hook_id"] == "nb1"

    @pytest.mark.asyncio
    async def test_nonblocking_failure_does_not_propagate(
        self,
        hooks_yaml: Path,
        failures_yaml: Path,
    ):
        """Non-blocking hook failure is logged but fire still returns success."""
        reg = _make_registry(
            [
                _hook("nb-fail", "trigger_a", "target_b", blocking=False),
            ]
        )
        save(reg, hooks_yaml)

        async def mock_fire(hook, source):
            return FireResult(
                hook_id=hook.id, status_code=500, body="error", error="internal error"
            )

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.storage._FAILURES_FILE", failures_yaml),
            patch("server.tools.fire._fire_single", side_effect=mock_fire),
        ):
            result = await hooks_fire("trigger_a")

        data = json.loads(result)
        # Fire returns success — no errors in the response
        assert data["errors"] == []
        assert data["hooks_fired"] == 0
        assert data["non_blocking_dispatched"] == 1

    @pytest.mark.asyncio
    async def test_nonblocking_exception_does_not_propagate(
        self,
        hooks_yaml: Path,
        failures_yaml: Path,
    ):
        """Non-blocking hook raising an exception does not crash fire."""
        reg = _make_registry(
            [
                _hook("nb-exc", "trigger_a", "target_b", blocking=False),
            ]
        )
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
        # Fire returns success — exception is caught inside _launch_nonblocking
        assert data["errors"] == []
        assert data["non_blocking_dispatched"] == 1

    @pytest.mark.asyncio
    async def test_background_tasks_set_lifecycle(self, hooks_yaml: Path):
        """Background task is added to _background_tasks and removed after completion."""
        import asyncio

        from server.tools.fire import _background_tasks

        reg = _make_registry(
            [
                _hook("nb-lc", "trigger_a", "target_b", blocking=False),
            ]
        )
        save(reg, hooks_yaml)

        async def mock_fire(hook, source):
            return FireResult(hook_id=hook.id, status_code=200, body="ok")

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.tools.fire._fire_single", side_effect=mock_fire),
        ):
            result = await hooks_fire("trigger_a")
            # Let the event loop process the background task and its done callback
            await asyncio.sleep(0.05)

        data = json.loads(result)
        assert data["non_blocking_dispatched"] == 1
        # After completion, the done_callback should have removed the task
        # (no tasks with our hook id should remain)
        assert all("nb-lc" not in str(t) for t in _background_tasks)

    @pytest.mark.asyncio
    async def test_nonblocking_logs_failure(self, hooks_yaml: Path, failures_yaml: Path):
        """Non-blocking hook HTTP failure is logged via storage.log_failure."""
        import asyncio

        reg = _make_registry(
            [
                _hook("nb-logf", "trigger_a", "target_b", blocking=False),
            ]
        )
        save(reg, hooks_yaml)

        async def mock_fire(hook, source):
            return FireResult(hook_id=hook.id, status_code=500, body="err", error="server error")

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.storage._FAILURES_FILE", failures_yaml),
            patch("server.tools.fire._fire_single", side_effect=mock_fire),
            patch("server.tools.fire.storage.log_failure") as mock_log_failure,
        ):
            result = await hooks_fire("trigger_a")
            await asyncio.sleep(0.05)

        data = json.loads(result)
        assert data["non_blocking_dispatched"] == 1
        mock_log_failure.assert_called_once()
        call_kwargs = mock_log_failure.call_args[1]
        assert call_kwargs["hook_id"] == "nb-logf"
        assert "server error" in call_kwargs["error"]

    @pytest.mark.asyncio
    async def test_all_nonblocking_no_blocking_results(self, hooks_yaml: Path):
        """When all hooks are non-blocking, hooks_fired=0 and results is empty."""
        reg = _make_registry(
            [
                _hook("nb1", "trigger_a", "target_1", blocking=False),
                _hook("nb2", "trigger_a", "target_2", blocking=False),
            ]
        )
        save(reg, hooks_yaml)

        async def mock_fire(hook, source):
            return FireResult(hook_id=hook.id, status_code=200, body="ok")

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.tools.fire._fire_single", side_effect=mock_fire),
        ):
            result = await hooks_fire("trigger_a")

        data = json.loads(result)
        assert data["hooks_fired"] == 0
        assert data["non_blocking_dispatched"] == 2
        assert len(data["results"]) == 2
        assert all(r["status"] == "dispatched" for r in data["results"])
        dispatched_ids = {r["hook_id"] for r in data["results"]}
        assert dispatched_ids == {"nb1", "nb2"}
        assert data["errors"] == []


class TestParentTodoistTaskIdGuard:
    """Tests for 399.1 — parent_todoist_task_id whitelist injection into base_config."""

    @pytest.mark.asyncio
    async def test_parent_todoist_task_id_injected_fires_condition(
        self,
        hooks_yaml: Path,
        proj_yaml: Path,
    ):
        """Hook with condition 'todo.parent_todoist_task_id' fires when source has it."""
        reg = _make_registry(
            [
                _hook(
                    "hook-parent",
                    "todo_add_child",
                    "todoist_add_child_task_hook",
                    condition=(
                        "sync.todoist.enabled and sync.todoist.auto_sync"
                        " and todo.parent_todoist_task_id"
                    ),
                ),
            ]
        )
        save(reg, hooks_yaml)
        proj_yaml.write_text(
            yaml.dump(
                {
                    "sync": {"todoist": {"enabled": True, "auto_sync": True}},
                }
            )
        )

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.conditions._PROJ_CONFIG_PATH", proj_yaml),
            patch(
                "server.tools.fire._fire_single",
                new_callable=AsyncMock,
                return_value=FireResult(hook_id="hook-parent", status_code=200, body="ok"),
            ),
        ):
            source = json.dumps({"parent_todoist_task_id": "abc123", "todoist_task_id": "child1"})
            result = await hooks_fire("todo_add_child", source_result=source)

        data = json.loads(result)
        # Should fire — all conditions met including parent_todoist_task_id
        assert data["non_blocking_dispatched"] == 1
        assert data["skipped"] == 0

    @pytest.mark.asyncio
    async def test_parent_todoist_task_id_absent_skips_condition(
        self,
        hooks_yaml: Path,
        proj_yaml: Path,
    ):
        """Hook with condition 'todo.parent_todoist_task_id' skips when source lacks it."""
        reg = _make_registry(
            [
                _hook(
                    "hook-parent",
                    "todo_add_child",
                    "todoist_add_child_task_hook",
                    condition=(
                        "sync.todoist.enabled and sync.todoist.auto_sync"
                        " and todo.parent_todoist_task_id"
                    ),
                ),
            ]
        )
        save(reg, hooks_yaml)
        proj_yaml.write_text(
            yaml.dump(
                {
                    "sync": {"todoist": {"enabled": True, "auto_sync": True}},
                }
            )
        )

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.conditions._PROJ_CONFIG_PATH", proj_yaml),
        ):
            # source_result does NOT contain parent_todoist_task_id
            source = json.dumps({"todoist_task_id": "child1"})
            result = await hooks_fire("todo_add_child", source_result=source)

        data = json.loads(result)
        # Should skip — parent_todoist_task_id missing evaluates to False
        assert data["hooks_fired"] == 0
        assert data["skipped"] == 1

    @pytest.mark.asyncio
    async def test_parent_todoist_task_id_empty_string_skips(
        self,
        hooks_yaml: Path,
        proj_yaml: Path,
    ):
        """Empty string for parent_todoist_task_id should evaluate as falsy → skip."""
        reg = _make_registry(
            [
                _hook(
                    "hook-parent",
                    "todo_add_child",
                    "todoist_add_child_task_hook",
                    condition="todo.parent_todoist_task_id",
                ),
            ]
        )
        save(reg, hooks_yaml)
        proj_yaml.write_text("")

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.conditions._PROJ_CONFIG_PATH", proj_yaml),
        ):
            source = json.dumps({"parent_todoist_task_id": ""})
            result = await hooks_fire("todo_add_child", source_result=source)

        data = json.loads(result)
        assert data["hooks_fired"] == 0
        assert data["skipped"] == 1


# ── Cascade dispatch tests ──────────────────────────────────────────────────


class TestCascadeDispatch:
    """Tests for cascade dispatch: blocking hooks trigger nested hooks on their target_tool."""

    @pytest.mark.asyncio
    async def test_cascade_b_fails_error_propagates(self, hooks_yaml: Path):
        """Hook A triggers hook B at depth 1; B fails ->
        error in cascade_errors with chain prefix."""
        # Hook A: trigger_a → target_b (blocking)
        # Hook B: target_b → target_c (blocking, will fail)
        reg = _make_registry(
            [
                _hook("hook-a", "trigger_a", "target_b", blocking=True),
                _hook("hook-b", "target_b", "target_c", blocking=True),
            ]
        )
        save(reg, hooks_yaml)

        call_count = 0

        async def mock_fire(hook, source):
            nonlocal call_count
            call_count += 1
            if hook.id == "hook-a":
                return FireResult(
                    hook_id="hook-a",
                    status_code=200,
                    body="ok",
                    result=json.dumps({"key": "from_a"}),
                )
            # hook-b fails
            return FireResult(
                hook_id="hook-b",
                status_code=500,
                body="error",
                error="target_c failed",
            )

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.tools.fire._fire_single", side_effect=mock_fire),
        ):
            result = await hooks_fire("trigger_a")

        data = json.loads(result)
        # Primary hook A fired successfully
        assert data["hooks_fired"] == 1
        assert data["errors"] == []
        assert len(data["results"]) == 1
        # Cascade error from B should be present
        assert "cascade_errors" in data
        assert len(data["cascade_errors"]) == 1
        assert "trigger_a" in data["cascade_errors"][0]
        assert "hook-a" in data["cascade_errors"][0]
        assert "target_b" in data["cascade_errors"][0]
        assert "target_c failed" in data["cascade_errors"][0]

    @pytest.mark.asyncio
    async def test_three_level_cascade_error_propagates(self, hooks_yaml: Path):
        """3-level cascade: A → B → C, C fails → error propagates all the way."""
        reg = _make_registry(
            [
                _hook("hook-a", "trigger_a", "target_b", blocking=True),
                _hook("hook-b", "target_b", "target_c", blocking=True),
                _hook("hook-c", "target_c", "target_d", blocking=True),
            ]
        )
        save(reg, hooks_yaml)

        async def mock_fire(hook, source):
            if hook.id == "hook-a":
                return FireResult(
                    hook_id="hook-a",
                    status_code=200,
                    body="ok",
                    result=json.dumps({"key": "from_a"}),
                )
            if hook.id == "hook-b":
                return FireResult(
                    hook_id="hook-b",
                    status_code=200,
                    body="ok",
                    result=json.dumps({"key": "from_b"}),
                )
            # hook-c fails
            return FireResult(
                hook_id="hook-c",
                status_code=500,
                body="error",
                error="target_d exploded",
            )

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.tools.fire._fire_single", side_effect=mock_fire),
        ):
            result = await hooks_fire("trigger_a")

        data = json.loads(result)
        assert data["hooks_fired"] == 1
        assert data["errors"] == []
        # The cascade error from C should propagate through B to A
        assert "cascade_errors" in data
        assert len(data["cascade_errors"]) >= 1
        # Should contain the chain path from the deepest level
        found = any("target_d exploded" in e for e in data["cascade_errors"])
        assert found, f"Expected 'target_d exploded' in cascade_errors: {data['cascade_errors']}"

    @pytest.mark.asyncio
    async def test_nonblocking_hooks_do_not_cascade(self, hooks_yaml: Path):
        """Non-blocking hooks should NOT trigger cascades."""
        reg = _make_registry(
            [
                _hook("hook-a", "trigger_a", "target_b", blocking=False),
                _hook("hook-b", "target_b", "target_c", blocking=True),
            ]
        )
        save(reg, hooks_yaml)

        call_ids: list[str] = []

        async def mock_fire(hook, source):
            call_ids.append(hook.id)
            return FireResult(hook_id=hook.id, status_code=200, body="ok")

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.tools.fire._fire_single", side_effect=mock_fire),
        ):
            result = await hooks_fire("trigger_a")

        data = json.loads(result)
        # hook-a is non-blocking, dispatched as background task
        assert data["non_blocking_dispatched"] == 1
        assert data["hooks_fired"] == 0
        # No cascade errors since non-blocking hooks don't cascade
        assert "cascade_errors" not in data

    @pytest.mark.asyncio
    async def test_cascade_stops_at_depth_limit(self, hooks_yaml: Path):
        """Cascade stops when depth + 1 >= max_depth."""
        reg = _make_registry(
            [
                _hook("hook-a", "trigger_a", "target_b", blocking=True),
                _hook("hook-b", "target_b", "target_c", blocking=True),
            ],
            settings={"max_depth": 2},
        )
        save(reg, hooks_yaml)

        call_ids: list[str] = []

        async def mock_fire(hook, source):
            call_ids.append(hook.id)
            return FireResult(
                hook_id=hook.id,
                status_code=200,
                body="ok",
                result=json.dumps({"key": f"from_{hook.id}"}),
            )

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.tools.fire._fire_single", side_effect=mock_fire),
        ):
            # depth=0, max_depth=2 → cascade at depth 1 is allowed, but depth 2 would stop
            result = await hooks_fire("trigger_a", depth=0)

        data = json.loads(result)
        # hook-a fires at depth 0, cascade fires hook-b at depth 1
        # At depth 1, hook-b result triggers cascade check:
        # depth+1=2 >= max_depth=2, so cascade stops
        assert "hook-a" in call_ids
        assert "hook-b" in call_ids
        # No cascade errors since everything succeeded
        assert data.get("cascade_errors") is None or data.get("cascade_errors") == []

    @pytest.mark.asyncio
    async def test_cascade_skips_non_dict_result(self, hooks_yaml: Path):
        """Cascade skips hooks whose result is not a JSON dict."""
        reg = _make_registry(
            [
                _hook("hook-a", "trigger_a", "target_b", blocking=True),
                _hook("hook-b", "target_b", "target_c", blocking=True),
            ]
        )
        save(reg, hooks_yaml)

        async def mock_fire(hook, source):
            if hook.id == "hook-a":
                # Return a non-dict JSON result
                return FireResult(
                    hook_id="hook-a",
                    status_code=200,
                    body="ok",
                    result=json.dumps([1, 2, 3]),
                )
            return FireResult(hook_id="hook-b", status_code=200, body="ok")

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.tools.fire._fire_single", side_effect=mock_fire),
        ):
            result = await hooks_fire("trigger_a")

        data = json.loads(result)
        assert data["hooks_fired"] == 1
        # No cascade because hook-a's result was a list, not a dict
        assert "cascade_errors" not in data

    @pytest.mark.asyncio
    async def test_cascade_errors_not_in_summary_when_empty(self, hooks_yaml: Path):
        """cascade_errors key should not appear in summary when there are none."""
        reg = _make_registry(
            [
                _hook("hook-a", "trigger_a", "target_b", blocking=True),
            ]
        )
        save(reg, hooks_yaml)

        async def mock_fire(hook, source):
            return FireResult(
                hook_id="hook-a",
                status_code=200,
                body="ok",
                result=json.dumps({"key": "val"}),
            )

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.tools.fire._fire_single", side_effect=mock_fire),
        ):
            result = await hooks_fire("trigger_a")

        data = json.loads(result)
        # No hooks match target_b, so no cascade fires, no cascade_errors key
        assert "cascade_errors" not in data


# ── Feedback writeback (Phase 1.5) ─────────────────────────────────────────


class TestFeedbackWriteback:
    """Tests for single-value and batch feedback writeback."""

    @pytest.mark.asyncio
    async def test_single_value_feedback_writeback(self, hooks_yaml: Path, failures_yaml: Path):
        """Blocking hook with feedback_mapping calls feedback_tool with mapped result."""
        hook_data = {
            "hooks": [
                {
                    "id": "h-fb",
                    "trigger_tool": "todo_add",
                    "target_tool": "todoist_add_tasks",
                    "server": "todoist",
                    "blocking": True,
                    "param_mapping": {},
                    "feedback_mapping": {"todoist_task_id": "todoist_task_id"},
                    "feedback_tool": "todo_update",
                }
            ]
        }
        hooks_yaml.write_text(yaml.dump(hook_data))

        feedback_calls: list[dict] = []

        async def mock_post_hook(*, hook_id, url, target_tool, params):
            if target_tool == "todo_update":
                feedback_calls.append({"hook_id": hook_id, "params": params})
                return FireResult(hook_id=hook_id, status_code=200, body="ok")
            # Primary hook returns a todoist_task_id
            return FireResult(
                hook_id=hook_id,
                status_code=200,
                body='{"todoist_task_id": "t999"}',
                result='{"todoist_task_id": "t999"}',
            )

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.storage._FAILURES_FILE", failures_yaml),
            patch("server.tools.fire._resolve_server_url", return_value="unix:///tmp/test.sock"),
            patch("server.tools.fire.post_hook", side_effect=mock_post_hook),
        ):
            result = await hooks_fire(
                "todo_add",
                source_result='{"todo_id": "my-todo", "project_name": "proj1"}',
                depth=0,
            )

        data = json.loads(result)
        assert "feedback" in data
        assert len(data["feedback"]) == 1
        assert data["feedback"][0]["ok"] is True
        # Verify feedback was called with correct mapped params
        assert len(feedback_calls) == 1
        assert feedback_calls[0]["params"]["todoist_task_id"] == "t999"
        assert feedback_calls[0]["params"]["todo_id"] == "my-todo"
        assert feedback_calls[0]["params"]["project_name"] == "proj1"

    @pytest.mark.asyncio
    async def test_feedback_skipped_when_no_result(self, hooks_yaml: Path, failures_yaml: Path):
        """Feedback writeback is skipped when blocking hook returns no extractable values."""
        hook_data = {
            "hooks": [
                {
                    "id": "h-fb",
                    "trigger_tool": "todo_add",
                    "target_tool": "todoist_add_tasks",
                    "server": "todoist",
                    "blocking": True,
                    "param_mapping": {},
                    "feedback_mapping": {"nonexistent_field": "todoist_task_id"},
                    "feedback_tool": "todo_update",
                }
            ]
        }
        hooks_yaml.write_text(yaml.dump(hook_data))

        async def mock_post_hook(*, hook_id, url, target_tool, params):
            return FireResult(
                hook_id=hook_id,
                status_code=200,
                body='{"other_field": "val"}',
                result='{"other_field": "val"}',
            )

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.storage._FAILURES_FILE", failures_yaml),
            patch("server.tools.fire._resolve_server_url", return_value="unix:///tmp/test.sock"),
            patch("server.tools.fire.post_hook", side_effect=mock_post_hook),
        ):
            result = await hooks_fire("todo_add", source_result='{"todo_id": "t1"}', depth=0)

        data = json.loads(result)
        # No feedback because mapped field didn't exist in result
        assert "feedback" not in data

    @pytest.mark.asyncio
    async def test_feedback_exception_logged_as_error(self, hooks_yaml: Path, failures_yaml: Path):
        """Exception during feedback writeback is caught and logged."""
        hook_data = {
            "hooks": [
                {
                    "id": "h-fb",
                    "trigger_tool": "todo_add",
                    "target_tool": "todoist_add_tasks",
                    "server": "todoist",
                    "blocking": True,
                    "param_mapping": {},
                    "feedback_mapping": {"todoist_task_id": "todoist_task_id"},
                    "feedback_tool": "todo_update",
                }
            ]
        }
        hooks_yaml.write_text(yaml.dump(hook_data))

        call_count = 0

        async def mock_post_hook(*, hook_id, url, target_tool, params):
            nonlocal call_count
            call_count += 1
            if target_tool == "todo_update":
                raise ConnectionError("feedback server down")
            return FireResult(
                hook_id=hook_id,
                status_code=200,
                body='{"todoist_task_id": "t1"}',
                result='{"todoist_task_id": "t1"}',
            )

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.storage._FAILURES_FILE", failures_yaml),
            patch("server.tools.fire._resolve_server_url", return_value="unix:///tmp/test.sock"),
            patch("server.tools.fire.post_hook", side_effect=mock_post_hook),
        ):
            result = await hooks_fire("todo_add", source_result='{"todo_id": "t1"}', depth=0)

        data = json.loads(result)
        assert "feedback" in data
        assert data["feedback"][0]["ok"] is False
        # Error should also be recorded
        assert any("feedback" in str(e.get("hook_id", "")) for e in data["errors"])


# ── Condition merge edge cases ─────────────────────────────────────────────


class TestConditionMergeEdgeCases:
    """Additional condition merge scenarios not covered by TestConditionMerge."""

    @pytest.mark.asyncio
    async def test_parent_todoist_task_id_merges_to_todo(self, hooks_yaml: Path, proj_yaml: Path):
        """parent_todoist_task_id from source_result merges into 'todo' section."""
        reg = _make_registry(
            [
                _hook("hook-001", "trigger_a", "target_b", condition="todo.parent_todoist_task_id"),
            ]
        )
        save(reg, hooks_yaml)
        proj_yaml.write_text("")

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.conditions._PROJ_CONFIG_PATH", proj_yaml),
            patch(
                "server.tools.fire._fire_single",
                new_callable=AsyncMock,
                return_value=FireResult(hook_id="hook-001", status_code=200, body="ok"),
            ),
        ):
            source = json.dumps({"parent_todoist_task_id": "parent123"})
            result = await hooks_fire("trigger_a", source_result=source)

        data = json.loads(result)
        assert data["non_blocking_dispatched"] == 1
        assert data["skipped"] == 0

    @pytest.mark.asyncio
    async def test_trello_checklist_item_id_merges_to_todo(self, hooks_yaml: Path, proj_yaml: Path):
        """trello_checklist_item_id from source_result merges into 'todo' section."""
        reg = _make_registry(
            [
                _hook(
                    "hook-001",
                    "trigger_a",
                    "target_b",
                    condition="todo.trello_checklist_item_id",
                ),
            ]
        )
        save(reg, hooks_yaml)
        proj_yaml.write_text("")

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.conditions._PROJ_CONFIG_PATH", proj_yaml),
            patch(
                "server.tools.fire._fire_single",
                new_callable=AsyncMock,
                return_value=FireResult(hook_id="hook-001", status_code=200, body="ok"),
            ),
        ):
            source = json.dumps({"trello_checklist_item_id": "item456"})
            result = await hooks_fire("trigger_a", source_result=source)

        data = json.loads(result)
        assert data["non_blocking_dispatched"] == 1
        assert data["skipped"] == 0

    @pytest.mark.asyncio
    async def test_empty_source_result_no_merge(self, hooks_yaml: Path, proj_yaml: Path):
        """Empty source_result does not inject any merge keys."""
        reg = _make_registry(
            [
                _hook("hook-001", "trigger_a", "target_b", condition="todo.todoist_task_id"),
            ]
        )
        save(reg, hooks_yaml)
        proj_yaml.write_text("")

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.conditions._PROJ_CONFIG_PATH", proj_yaml),
        ):
            result = await hooks_fire("trigger_a", source_result="{}")

        data = json.loads(result)
        assert data["skipped"] == 1


# ── Depth limit correctness ─────────────────────────────────────────────────


class TestDepthLimit:
    """Verify that exactly max_depth cascade levels execute (no off-by-one)."""

    def _make_chain_registry(self, length: int, hooks_yaml: Path) -> None:
        """Create a hook chain: trigger_0 → hook-0 → trigger_1 → hook-1 → …"""
        hooks = []
        servers: dict[str, dict[str, str]] = {}
        for i in range(length):
            hooks.append(
                Hook(
                    id=f"hook-{i:03d}",
                    trigger_tool=f"trigger_{i}",
                    target_tool=f"trigger_{i + 1}",
                    server="s",
                    blocking=True,
                )
            )
        servers["s"] = {"url": "http://localhost:19100/hook"}
        save(HookRegistry(hooks=hooks, servers=servers), hooks_yaml)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("max_depth", [1, 2, 3])
    async def test_depth_limit_exact_levels(
        self, hooks_yaml: Path, proj_yaml: Path, max_depth: int
    ):
        """Exactly max_depth cascade levels execute; depth max_depth is blocked."""
        # Build a chain longer than max_depth so the limit is always exercised
        self._make_chain_registry(max_depth + 2, hooks_yaml)
        proj_yaml.write_text("")

        fired_hook_ids: list[str] = []

        async def capturing_post_hook(
            *, hook_id: str, url: str, target_tool: str, params: dict
        ) -> FireResult:
            fired_hook_ids.append(hook_id)
            return FireResult(hook_id=hook_id, status_code=200, body="{}", result="{}")

        mock_post = AsyncMock(side_effect=capturing_post_hook)

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.conditions._PROJ_CONFIG_PATH", proj_yaml),
            patch("server.tools.fire._get_max_depth", return_value=max_depth),
            patch("server.tools.fire.post_hook", mock_post),
        ):
            await hooks_fire("trigger_0", source_result="{}")

        # Exactly max_depth hooks should have fired (depths 0 … max_depth-1)
        assert len(fired_hook_ids) == max_depth, (
            f"Expected {max_depth} hooks fired, got {len(fired_hook_ids)}"
        )
