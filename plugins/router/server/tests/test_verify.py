"""Tests for server.tools.verify — explicit verification hook firing."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from server.lib.http_client import FireResult
from server.lib.models import Hook, HookRegistry
from server.lib.storage import save
from server.tools.verify import hooks_verify

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_registry(hooks: list[Hook], servers: dict | None = None):
    return HookRegistry(hooks=hooks, servers=servers or {})


def _hook(
    hook_id: str,
    trigger: str,
    target: str,
    server: str = "srv",
    *,
    blocking: bool = False,
    verification: bool = False,
    condition: str | None = None,
    param_mapping: dict | None = None,
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


class TestHooksVerify:
    @pytest.mark.asyncio
    async def test_no_verification_hooks(self, hooks_yaml: Path):
        """Returns no_verification_hooks when none are registered."""
        reg = _make_registry(
            [
                _hook("hook-001", "trigger_a", "target_b", blocking=True),
            ]
        )
        save(reg, hooks_yaml)

        with patch("server.lib.storage._HOOKS_FILE", hooks_yaml):
            result = await hooks_verify("trigger_a")

        data = json.loads(result)
        assert data["status"] == "no_verification_hooks"
        assert data["trigger"] == "trigger_a"

    @pytest.mark.asyncio
    async def test_no_hooks_at_all(self, hooks_yaml: Path):
        """Returns no_verification_hooks for empty registry."""
        save(HookRegistry(), hooks_yaml)

        with patch("server.lib.storage._HOOKS_FILE", hooks_yaml):
            result = await hooks_verify("nonexistent")

        data = json.loads(result)
        assert data["status"] == "no_verification_hooks"
        assert data["trigger"] == "nonexistent"

    @pytest.mark.asyncio
    async def test_fires_verification_hooks_pass(
        self,
        hooks_yaml: Path,
        verifications_yaml: Path,
    ):
        """Verification hook returning pass is reported correctly."""
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
            result = await hooks_verify("trigger_a")

        data = json.loads(result)
        assert len(data["results"]) == 1
        assert data["results"][0]["hook_id"] == "verify-001"
        assert data["results"][0]["status"] == "pass"
        assert data["results"][0]["details"] == "confirmed"
        assert data["summary"]["total"] == 1
        assert data["summary"]["passed"] == 1
        assert data["summary"]["failed"] == 0

    @pytest.mark.asyncio
    async def test_fires_verification_hooks_fail(
        self,
        hooks_yaml: Path,
        verifications_yaml: Path,
    ):
        """Verification hook returning fail is reported correctly."""
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
            result = await hooks_verify("trigger_a")

        data = json.loads(result)
        assert data["results"][0]["status"] == "fail"
        assert data["results"][0]["details"] == "task still open"
        assert data["summary"]["passed"] == 0
        assert data["summary"]["failed"] == 1

    @pytest.mark.asyncio
    async def test_multiple_verification_hooks_mixed_results(
        self,
        hooks_yaml: Path,
        verifications_yaml: Path,
    ):
        """Multiple verification hooks with mixed pass/fail results."""
        reg = _make_registry(
            [
                _hook("verify-001", "trigger_a", "verify_a", verification=True),
                _hook("verify-002", "trigger_a", "verify_b", verification=True),
                _hook("verify-003", "trigger_a", "verify_c", verification=True),
            ]
        )
        save(reg, hooks_yaml)

        async def mock_fire_single(hook, source):
            if hook.id == "verify-002":
                return FireResult(
                    hook_id=hook.id,
                    status_code=200,
                    body="ok",
                    result=json.dumps({"status": "fail", "details": "check failed"}),
                )
            return FireResult(
                hook_id=hook.id,
                status_code=200,
                body="ok",
                result=json.dumps({"status": "pass", "details": "ok"}),
            )

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.storage._VERIFICATIONS_FILE", verifications_yaml),
            patch("server.tools.fire._fire_single", side_effect=mock_fire_single),
        ):
            result = await hooks_verify("trigger_a")

        data = json.loads(result)
        assert data["summary"]["total"] == 3
        assert data["summary"]["passed"] == 2
        assert data["summary"]["failed"] == 1

    @pytest.mark.asyncio
    async def test_only_fires_matching_trigger(
        self,
        hooks_yaml: Path,
        verifications_yaml: Path,
    ):
        """Only fires verification hooks for the specified trigger_tool."""
        reg = _make_registry(
            [
                _hook("verify-001", "trigger_a", "verify_a", verification=True),
                _hook("verify-002", "trigger_b", "verify_b", verification=True),
            ]
        )
        save(reg, hooks_yaml)

        fired_hooks: list[str] = []

        async def mock_fire_single(hook, source):
            fired_hooks.append(hook.id)
            return FireResult(
                hook_id=hook.id,
                status_code=200,
                body="ok",
                result=json.dumps({"status": "pass", "details": "ok"}),
            )

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.storage._VERIFICATIONS_FILE", verifications_yaml),
            patch("server.tools.fire._fire_single", side_effect=mock_fire_single),
        ):
            result = await hooks_verify("trigger_a")

        data = json.loads(result)
        assert data["summary"]["total"] == 1
        assert fired_hooks == ["verify-001"]

    @pytest.mark.asyncio
    async def test_ignores_primary_hooks(
        self,
        hooks_yaml: Path,
        verifications_yaml: Path,
    ):
        """Primary (non-verification) hooks are not fired."""
        reg = _make_registry(
            [
                _hook("hook-001", "trigger_a", "target_b", blocking=True),
                _hook("verify-001", "trigger_a", "verify_target", verification=True),
            ]
        )
        save(reg, hooks_yaml)

        fired_hooks: list[str] = []

        async def mock_fire_single(hook, source):
            fired_hooks.append(hook.id)
            return FireResult(
                hook_id=hook.id,
                status_code=200,
                body="ok",
                result=json.dumps({"status": "pass", "details": "ok"}),
            )

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.storage._VERIFICATIONS_FILE", verifications_yaml),
            patch("server.tools.fire._fire_single", side_effect=mock_fire_single),
        ):
            result = await hooks_verify("trigger_a")

        data = json.loads(result)
        assert data["summary"]["total"] == 1
        assert fired_hooks == ["verify-001"]

    @pytest.mark.asyncio
    async def test_source_result_passed_to_hooks(
        self,
        hooks_yaml: Path,
        verifications_yaml: Path,
    ):
        """source_result is parsed and passed to verification hooks."""
        reg = _make_registry(
            [
                _hook("verify-001", "trigger_a", "verify_target", verification=True),
            ]
        )
        save(reg, hooks_yaml)

        captured_source: dict = {}

        async def mock_fire_single(hook, source):
            captured_source.update(source)
            return FireResult(
                hook_id=hook.id,
                status_code=200,
                body="ok",
                result=json.dumps({"status": "pass", "details": "ok"}),
            )

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.storage._VERIFICATIONS_FILE", verifications_yaml),
            patch("server.tools.fire._fire_single", side_effect=mock_fire_single),
        ):
            await hooks_verify("trigger_a", source_result='{"key": "val", "num": 42}')

        assert captured_source["key"] == "val"
        assert captured_source["num"] == 42

    @pytest.mark.asyncio
    async def test_http_error_treated_as_fail(
        self,
        hooks_yaml: Path,
        failures_yaml: Path,
        verifications_yaml: Path,
    ):
        """HTTP error on verification hook results in fail status."""
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
            result = await hooks_verify("trigger_a")

        data = json.loads(result)
        assert data["results"][0]["status"] == "fail"
        assert "HTTP 500" in data["results"][0]["details"]
        assert data["summary"]["failed"] == 1

    @pytest.mark.asyncio
    async def test_exception_treated_as_fail(
        self,
        hooks_yaml: Path,
        failures_yaml: Path,
        verifications_yaml: Path,
    ):
        """Exception during verification hook fire results in fail status."""
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
            result = await hooks_verify("trigger_a")

        data = json.loads(result)
        assert data["results"][0]["status"] == "fail"
        assert "Exception" in data["results"][0]["details"]
        assert data["summary"]["failed"] == 1

    @pytest.mark.asyncio
    async def test_malformed_response_treated_as_fail(
        self,
        hooks_yaml: Path,
        verifications_yaml: Path,
    ):
        """Malformed response (missing status field) results in fail."""
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
            result = await hooks_verify("trigger_a")

        data = json.loads(result)
        assert data["results"][0]["status"] == "fail"
        assert data["summary"]["failed"] == 1

    @pytest.mark.asyncio
    async def test_results_stored_in_verifications_file(
        self,
        hooks_yaml: Path,
        verifications_yaml: Path,
    ):
        """Verification results are persisted to the verifications file."""
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
                result=json.dumps({"status": "pass", "details": "stored"}),
            )

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.storage._VERIFICATIONS_FILE", verifications_yaml),
            patch("server.tools.fire._fire_single", side_effect=mock_fire_single),
        ):
            await hooks_verify("trigger_a")

        from server.lib.storage import load_verification_results

        with patch("server.lib.storage._VERIFICATIONS_FILE", verifications_yaml):
            entries = load_verification_results()
        assert len(entries) == 1
        assert entries[0]["hook_id"] == "verify-001"
        assert entries[0]["status"] == "pass"
        assert entries[0]["trigger_tool"] == "trigger_a"

    @pytest.mark.asyncio
    async def test_invalid_source_result_json(self, hooks_yaml: Path):
        """Invalid JSON in source_result returns error."""
        save(HookRegistry(), hooks_yaml)
        with patch("server.lib.storage._HOOKS_FILE", hooks_yaml):
            result = await hooks_verify("trigger_a", source_result="not-json")
        assert "Error" in result
        assert "not valid JSON" in result

    @pytest.mark.asyncio
    async def test_non_dict_source_result(self, hooks_yaml: Path):
        """Non-dict JSON in source_result returns error."""
        save(HookRegistry(), hooks_yaml)
        with patch("server.lib.storage._HOOKS_FILE", hooks_yaml):
            result = await hooks_verify("trigger_a", source_result="[1, 2]")
        assert "Error" in result
        assert "must be a JSON object" in result

    @pytest.mark.asyncio
    async def test_condition_filtering(
        self,
        hooks_yaml: Path,
        proj_yaml: Path,
        verifications_yaml: Path,
    ):
        """Verification hooks with false conditions are skipped."""
        reg = _make_registry(
            [
                _hook(
                    "verify-001",
                    "trigger_a",
                    "verify_target",
                    verification=True,
                    condition="feature.enabled",
                ),
            ]
        )
        save(reg, hooks_yaml)
        proj_yaml.write_text("")  # Empty config -> condition False

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.storage._VERIFICATIONS_FILE", verifications_yaml),
            patch("server.lib.conditions._PROJ_CONFIG_PATH", proj_yaml),
        ):
            result = await hooks_verify("trigger_a")

        data = json.loads(result)
        # _fire_verification filters by condition internally, returns empty results
        assert data["results"] == []
        assert data["summary"]["total"] == 0
        assert data["summary"]["passed"] == 0
        assert data["summary"]["failed"] == 0
