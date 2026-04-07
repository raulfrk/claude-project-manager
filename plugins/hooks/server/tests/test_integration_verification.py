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
from server.tools.verify import hooks_verify

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
    async def test_verification_not_fired_when_no_verification_hooks(
        self,
        hooks_yaml: Path,
        failures_yaml: Path,
    ):
        """When only primary hooks exist, no verification section in response."""
        reg = _make_registry(
            [
                _hook("primary-001", "trigger_a", "target_a", blocking=True),
            ]
        )
        save(reg, hooks_yaml)

        async def mock_fire_single(hook, source):
            return FireResult(
                hook_id=hook.id,
                status_code=200,
                body="ok",
                result="done",
            )

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.storage._FAILURES_FILE", failures_yaml),
            patch("server.tools.fire._fire_single", side_effect=mock_fire_single),
        ):
            raw = await hooks_fire("trigger_a")

        data = json.loads(raw)
        assert data["hooks_fired"] == 1
        assert "verification" not in data

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


# ── Test 4: Explicit hooks_verify tool ────────────────────────────────────


class TestExplicitHooksVerify:
    """Call hooks_verify_tool directly and confirm structured results."""

    @pytest.mark.asyncio
    async def test_hooks_verify_returns_structured_summary(
        self,
        hooks_yaml: Path,
        verifications_yaml: Path,
    ):
        """hooks_verify returns results array and summary with total/passed/failed."""
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
            raw = await hooks_verify("trigger_a")

        data = json.loads(raw)

        # Structured results
        assert len(data["results"]) == 3
        hook_ids = {r["hook_id"] for r in data["results"]}
        assert hook_ids == {"verify-001", "verify-002", "verify-003"}

        # Summary tallies
        assert data["summary"]["total"] == 3
        assert data["summary"]["passed"] == 2
        assert data["summary"]["failed"] == 1

    @pytest.mark.asyncio
    async def test_hooks_verify_stores_results(
        self,
        hooks_yaml: Path,
        verifications_yaml: Path,
    ):
        """hooks_verify stores all verification results to verifications yaml."""
        reg = _make_registry(
            [
                _hook("verify-001", "trigger_a", "verify_a", verification=True),
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
            await hooks_verify("trigger_a")

        entries = load_verification_results(path=verifications_yaml)
        assert len(entries) == 1
        assert entries[0]["hook_id"] == "verify-001"
        assert entries[0]["status"] == "pass"
        assert entries[0]["trigger_tool"] == "trigger_a"
        assert entries[0]["details"] == "confirmed"

    @pytest.mark.asyncio
    async def test_hooks_verify_no_verification_hooks_registered(
        self,
        hooks_yaml: Path,
    ):
        """hooks_verify with no verification hooks returns appropriate status."""
        reg = _make_registry(
            [
                _hook("primary-001", "trigger_a", "target_b", blocking=True),
            ]
        )
        save(reg, hooks_yaml)

        with patch("server.lib.storage._HOOKS_FILE", hooks_yaml):
            raw = await hooks_verify("trigger_a")

        data = json.loads(raw)
        assert data["status"] == "no_verification_hooks"
        assert data["trigger"] == "trigger_a"

    @pytest.mark.asyncio
    async def test_hooks_verify_does_not_fire_primary_hooks(
        self,
        hooks_yaml: Path,
        verifications_yaml: Path,
    ):
        """hooks_verify only fires verification hooks, not primary ones."""
        reg = _make_registry(
            [
                _hook("primary-001", "trigger_a", "target_b", blocking=True),
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
            await hooks_verify("trigger_a")

        # Only verification hook fired
        assert fired_hooks == ["verify-001"]


# ── Additional integration scenarios ──────────────────────────────────────


class TestVerificationRegistrationIntegration:
    """Registration mechanics for verification hooks via hooks_register."""

    def test_register_verification_forces_blocking(self, hooks_yaml: Path):
        """Registering a verification hook sets blocking=True automatically."""
        with patch("server.lib.storage._HOOKS_FILE", hooks_yaml):
            result = hooks_register(
                trigger_tool="proj_init",
                target_tool="verify_perms",
                server="perms",
                verification=True,
                blocking=False,  # explicitly False, should be overridden
            )

        assert "Registered" in result
        assert "blocking: True" in result
        assert "verification: True" in result

        # Verify in loaded registry
        reg = load(hooks_yaml)
        hook = reg.find_by_id("hook-001")
        assert hook is not None
        assert hook.verification is True
        assert hook.blocking is True

    def test_list_separates_primary_and_verification(self, hooks_yaml: Path):
        """hooks_list returns primary hooks and verification hooks separately."""
        from server.tools.registry import hooks_list

        with patch("server.lib.storage._HOOKS_FILE", hooks_yaml):
            hooks_register(
                trigger_tool="proj_init",
                target_tool="perms_setup",
                server="perms",
                blocking=True,
            )
            hooks_register(
                trigger_tool="proj_init",
                target_tool="verify_perms",
                server="perms",
                verification=True,
            )

        with patch("server.lib.storage._HOOKS_FILE", hooks_yaml):
            raw = hooks_list()

        data = json.loads(raw)
        assert len(data["hooks"]) == 1
        assert data["hooks"][0]["id"] == "hook-001"
        assert len(data["verification_hooks"]) == 1
        assert data["verification_hooks"][0]["id"] == "hook-002"
        assert data["verification_hooks"][0]["verification"] is True

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
