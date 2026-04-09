"""Integration tests for verification hooks — end-to-end scenarios."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from server.lib.http_client import FireResult
from server.lib.models import Hook, HookRegistry
from server.lib.storage import load, load_failures, load_verification_results, save
from server.tools.fire import hooks_fire
from server.tools.recovery import hooks_recover
from server.tools.registry import hooks_register, hooks_unregister

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_registry(hooks: list[Hook], servers: dict | None = None) -> HookRegistry:
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


# ── Test 1: Full lifecycle — register, fire, verify results stored ────────


class TestFullLifecycle:
    """Register primary + verification hooks, fire, confirm Phase 1 then Phase 2."""

    @pytest.mark.asyncio
    async def test_register_fire_verify_stored(
        self,
        hooks_yaml: Path,
        failures_yaml: Path,
        verifications_yaml: Path,
    ):
        """Full lifecycle: register primary + verification, fire trigger,
        confirm Phase 1 fires first, Phase 2 fires after with aggregated results,
        and verification result is stored in verifications yaml.
        """
        # Register a primary blocking hook
        with patch("server.lib.storage._HOOKS_FILE", hooks_yaml):
            r1 = hooks_register(
                trigger_tool="proj_init",
                target_tool="perms_setup",
                server="perms",
                blocking=True,
            )
        assert "Registered" in r1

        # Register a verification hook for the same trigger
        with patch("server.lib.storage._HOOKS_FILE", hooks_yaml):
            r2 = hooks_register(
                trigger_tool="proj_init",
                target_tool="verify_perms",
                server="perms",
                verification=True,
            )
        assert "Registered" in r2
        assert "verification: True" in r2

        # Track call order to confirm Phase 1 before Phase 2
        call_order: list[str] = []

        async def mock_fire_single(hook, source):
            call_order.append(hook.id)
            if hook.verification:
                # Verification hook returns convention-based pass
                return FireResult(
                    hook_id=hook.id,
                    status_code=200,
                    body="ok",
                    result=json.dumps({"status": "pass", "details": "perms verified"}),
                )
            # Primary hook returns a normal result
            return FireResult(
                hook_id=hook.id,
                status_code=200,
                body="ok",
                result="perms setup complete",
            )

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.storage._FAILURES_FILE", failures_yaml),
            patch("server.lib.storage._VERIFICATIONS_FILE", verifications_yaml),
            patch("server.tools.fire._fire_single", side_effect=mock_fire_single),
        ):
            raw = await hooks_fire("proj_init", source_result='{"path": "/tmp"}')

        data = json.loads(raw)

        # Phase 1 primary hook fired
        assert data["hooks_fired"] == 1
        assert data["errors"] == []
        assert len(data["results"]) == 1
        assert data["results"][0]["hook_id"] == "hook-001"

        # Phase 2 verification fired and included in response
        assert "verification" in data
        assert len(data["verification"]) == 1
        assert data["verification"][0]["status"] == "pass"
        assert data["verification"][0]["details"] == "perms verified"

        # Confirm ordering: primary (hook-001) before verification (hook-002)
        assert call_order.index("hook-001") < call_order.index("hook-002")

        # Confirm verification result stored in verifications yaml
        entries = load_verification_results(path=verifications_yaml)
        assert len(entries) == 1
        assert entries[0]["hook_id"] == "hook-002"
        assert entries[0]["trigger_tool"] == "proj_init"
        assert entries[0]["status"] == "pass"
        assert entries[0]["details"] == "perms verified"

    @pytest.mark.asyncio
    async def test_verification_receives_aggregated_hook_results(
        self,
        hooks_yaml: Path,
        failures_yaml: Path,
        verifications_yaml: Path,
    ):
        """Verification hooks receive Phase 1 blocking results via hook_results key."""
        reg = _make_registry(
            [
                _hook("primary-001", "trigger_a", "target_b", blocking=True),
                _hook("verify-001", "trigger_a", "verify_target", verification=True),
            ]
        )
        save(reg, hooks_yaml)

        captured_verification_source: dict = {}

        async def mock_fire_single(hook, source):
            if hook.verification:
                captured_verification_source.update(source)
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
                result="primary result value",
            )

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.storage._FAILURES_FILE", failures_yaml),
            patch("server.lib.storage._VERIFICATIONS_FILE", verifications_yaml),
            patch("server.tools.fire._fire_single", side_effect=mock_fire_single),
        ):
            await hooks_fire("trigger_a", source_result='{"key": "val"}')

        # Verification hook should receive the original source + hook_results
        assert "key" in captured_verification_source
        assert captured_verification_source["key"] == "val"
        assert "hook_results" in captured_verification_source
        assert "primary-001" in captured_verification_source["hook_results"]
        assert captured_verification_source["hook_results"]["primary-001"] == "primary result value"


# ── Test 2: Verification failure -> hooks-recover ─────────────────────────


class TestVerificationFailureRecovery:
    """Verification failure is logged and appears in hooks-recover."""

    @pytest.mark.asyncio
    async def test_verification_failure_logged_and_recoverable(
        self,
        hooks_yaml: Path,
        failures_yaml: Path,
        verifications_yaml: Path,
    ):
        """Verification hook that fails logs to failures + verifications,
        and the failure appears in hooks_recover list output.
        """
        reg = _make_registry(
            [
                _hook("verify-001", "trigger_a", "verify_target", verification=True),
            ]
        )
        save(reg, hooks_yaml)

        # Verification hook returns HTTP error
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
            raw = await hooks_fire("trigger_a")

        json.loads(raw)

        # Verification result stored as fail
        v_entries = load_verification_results(path=verifications_yaml)
        assert len(v_entries) == 1
        assert v_entries[0]["status"] == "fail"
        assert "HTTP 500" in v_entries[0]["details"]

        # Failure logged in failures yaml
        failures = load_failures(failures_yaml)
        assert len(failures) == 1
        assert failures[0]["hook_id"] == "verify-001"

        # hooks_recover lists the failure
        with patch("server.lib.storage._FAILURES_FILE", failures_yaml):
            recover_raw = await hooks_recover()

        recover_data = json.loads(recover_raw)
        assert len(recover_data) == 1
        assert recover_data[0]["hook_id"] == "verify-001"

    @pytest.mark.asyncio
    async def test_verification_failure_convention_response(
        self,
        hooks_yaml: Path,
        failures_yaml: Path,
        verifications_yaml: Path,
    ):
        """Verification hook returning {"status": "fail", "details": "..."} via
        convention-based response — failure stored but not in failures yaml
        (only HTTP/transport errors log to failures).
        """
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
            patch("server.lib.storage._FAILURES_FILE", failures_yaml),
            patch("server.lib.storage._VERIFICATIONS_FILE", verifications_yaml),
            patch("server.tools.fire._fire_single", side_effect=mock_fire_single),
        ):
            raw = await hooks_fire("trigger_a")

        json.loads(raw)

        # Verification stored as fail
        v_entries = load_verification_results(path=verifications_yaml)
        assert len(v_entries) == 1
        assert v_entries[0]["status"] == "fail"
        assert v_entries[0]["details"] == "task still open"

        # Convention-based fail does NOT log to failures (only transport errors do)
        failures = load_failures(failures_yaml)
        assert len(failures) == 0


# ── Test 3: Mixed primary + verification hooks ───────────────────────────


class TestMixedPrimaryVerification:
    """Multiple primary + verification hooks fire in correct order."""

    @pytest.mark.asyncio
    async def test_all_primary_before_verification(
        self,
        hooks_yaml: Path,
        failures_yaml: Path,
        verifications_yaml: Path,
    ):
        """Multiple primary hooks (blocking + non-blocking) fire before
        any verification hooks.
        """
        reg = _make_registry(
            [
                _hook("primary-001", "trigger_a", "target_a", blocking=True),
                _hook("primary-002", "trigger_a", "target_b", blocking=True),
                _hook("verify-001", "trigger_a", "verify_a", verification=True),
                _hook("verify-002", "trigger_a", "verify_b", verification=True),
            ]
        )
        save(reg, hooks_yaml)

        call_order: list[str] = []

        async def mock_fire_single(hook, source):
            call_order.append(hook.id)
            if hook.verification:
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
                result="primary done",
            )

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.storage._FAILURES_FILE", failures_yaml),
            patch("server.lib.storage._VERIFICATIONS_FILE", verifications_yaml),
            patch("server.tools.fire._fire_single", side_effect=mock_fire_single),
        ):
            raw = await hooks_fire("trigger_a")

        data = json.loads(raw)

        # Both primary hooks fired
        assert data["hooks_fired"] == 2
        assert len(data["results"]) == 2

        # Both verification hooks fired
        assert len(data["verification"]) == 2

        # All primary hooks appear before any verification hook in call_order
        primary_indices = [call_order.index(h) for h in ("primary-001", "primary-002")]
        verify_indices = [call_order.index(h) for h in ("verify-001", "verify-002")]
        assert max(primary_indices) < min(verify_indices)

    @pytest.mark.asyncio
    async def test_verification_fires_even_when_primary_fails(
        self,
        hooks_yaml: Path,
        failures_yaml: Path,
        verifications_yaml: Path,
    ):
        """Verification hooks fire even if a primary blocking hook errors."""
        reg = _make_registry(
            [
                _hook("primary-001", "trigger_a", "target_a", blocking=True),
                _hook("verify-001", "trigger_a", "verify_a", verification=True),
            ]
        )
        save(reg, hooks_yaml)

        call_order: list[str] = []

        async def mock_fire_single(hook, source):
            call_order.append(hook.id)
            if hook.id == "primary-001":
                return FireResult(
                    hook_id=hook.id,
                    status_code=500,
                    body="error",
                    error="HTTP 500",
                )
            return FireResult(
                hook_id=hook.id,
                status_code=200,
                body="ok",
                result=json.dumps({"status": "pass", "details": "verified"}),
            )

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.storage._FAILURES_FILE", failures_yaml),
            patch("server.lib.storage._VERIFICATIONS_FILE", verifications_yaml),
            patch("server.tools.fire._fire_single", side_effect=mock_fire_single),
        ):
            raw = await hooks_fire("trigger_a")

        data = json.loads(raw)

        # Primary fired with error
        assert data["hooks_fired"] == 1
        assert len(data["errors"]) == 1

        # Verification still fired
        assert "verification" in data
        assert len(data["verification"]) == 1
        assert data["verification"][0]["status"] == "pass"

        # Ordering maintained
        assert call_order.index("primary-001") < call_order.index("verify-001")


class TestVerificationRetryRecovery:
    """Verification hook fails on fire, then succeeds on retry via hooks_recover."""

    @pytest.mark.asyncio
    async def test_verification_fail_then_retry_success(
        self,
        hooks_yaml: Path,
        failures_yaml: Path,
        verifications_yaml: Path,
    ):
        """Verification hook HTTP-fails, failure logged, retry succeeds and clears."""
        reg = _make_registry(
            [
                _hook("verify-001", "trigger_a", "verify_target", verification=True),
            ]
        )
        save(reg, hooks_yaml)

        # Phase 1: fire — verification hook fails
        async def mock_fire_fail(hook, source):
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
            patch("server.tools.fire._fire_single", side_effect=mock_fire_fail),
        ):
            await hooks_fire("trigger_a")

        failures = load_failures(failures_yaml)
        assert len(failures) == 1
        assert failures[0]["hook_id"] == "verify-001"

        # Phase 2: retry via hooks_recover — succeeds
        from unittest.mock import AsyncMock

        success = FireResult(hook_id="verify-001", status_code=200, body="ok")
        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.storage._FAILURES_FILE", failures_yaml),
            patch(
                "server.tools.recovery.post_hook",
                new_callable=AsyncMock,
                return_value=success,
            ),
        ):
            r = await hooks_recover(hook_id="verify-001")

        rdata = json.loads(r)
        assert rdata["retried"] == 1
        assert rdata["succeeded"] == 1

        remaining = load_failures(failures_yaml)
        assert len(remaining) == 0


class TestVerificationUnregister:
    """Unregister verification hook and confirm it no longer fires."""

    def test_unregister_verification_hook(self, hooks_yaml: Path):
        """Verification hooks can be unregistered like primary hooks."""
        with patch("server.lib.storage._HOOKS_FILE", hooks_yaml):
            hooks_register(
                trigger_tool="proj_init",
                target_tool="verify_perms",
                server="perms",
                verification=True,
            )

        with patch("server.lib.storage._HOOKS_FILE", hooks_yaml):
            result = hooks_unregister("hook-001")
        assert "Unregistered" in result

        reg = load(hooks_yaml)
        assert len(reg.hooks) == 0
