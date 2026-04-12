"""Tests for server.tools.recovery — hook failure recovery."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from server.lib.http_client import FireResult
from server.lib.models import Hook, HookRegistry
from server.lib.storage import log_failure, save
from server.tools.recovery import _retry_entry, hooks_recover

# ── _retry_entry ───────────────────────────────────────────────────────────


class TestRetryEntry:
    @pytest.mark.asyncio
    async def test_deleted_hook_returns_false_and_logs_warning(
        self, hooks_yaml: Path, caplog: pytest.LogCaptureFixture
    ):
        """When the hook is not in the registry, _retry_entry returns False,
        logs a warning, and does NOT call post_hook."""
        # Empty registry — no hooks registered
        reg = HookRegistry()
        save(reg, hooks_yaml)

        entry = {
            "hook_id": "hook-999",
            "target_tool": "some_target",
            "server": "some_server",
            "source_result": "{}",
        }

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.tools.recovery.post_hook", new_callable=AsyncMock) as mock_post,
            caplog.at_level(logging.WARNING),
        ):
            result = await _retry_entry(entry)

        assert result is False
        assert "hook-999" in caplog.text
        assert "not found" in caplog.text.lower()
        mock_post.assert_not_called()

    @pytest.mark.asyncio
    async def test_existing_hook_calls_post_hook(self, hooks_yaml: Path):
        """When the hook exists, _retry_entry resolves params and calls post_hook."""
        hook = Hook(
            id="hook-001",
            trigger_tool="trigger_a",
            target_tool="target_b",
            server="srv",
            param_mapping={"key": "${val}"},
        )
        reg = HookRegistry(
            hooks=[hook],
            servers={"srv": {"url": "http://localhost:9999/hook"}},
        )
        save(reg, hooks_yaml)

        entry = {
            "hook_id": "hook-001",
            "target_tool": "target_b",
            "server": "srv",
            "source_result": json.dumps({"val": "resolved_value"}),
        }

        mock_result = FireResult(hook_id="hook-001", status_code=200, result="{}")

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch(
                "server.tools.recovery.post_hook",
                new_callable=AsyncMock,
                return_value=mock_result,
            ) as mock_post,
        ):
            result = await _retry_entry(entry)

        assert result is True
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["params"] == {"key": "resolved_value"}

    @pytest.mark.asyncio
    async def test_existing_hook_post_failure_returns_false(self, hooks_yaml: Path):
        """When post_hook returns ok=False, _retry_entry returns False."""
        hook = Hook(
            id="hook-001",
            trigger_tool="trigger_a",
            target_tool="target_b",
            server="srv",
        )
        reg = HookRegistry(hooks=[hook], servers={"srv": {"url": "http://localhost:9999/hook"}})
        save(reg, hooks_yaml)

        entry = {
            "hook_id": "hook-001",
            "target_tool": "target_b",
            "server": "srv",
            "source_result": "{}",
        }

        mock_result = FireResult(hook_id="hook-001", status_code=500, error="server error")

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch(
                "server.tools.recovery.post_hook",
                new_callable=AsyncMock,
                return_value=mock_result,
            ),
        ):
            result = await _retry_entry(entry)

        assert result is False


# ── hooks_recover integration ──────────────────────────────────────────────


class TestHooksRecover:
    @pytest.mark.asyncio
    async def test_recover_deleted_hook_marks_still_failed(
        self, hooks_yaml: Path, failures_yaml: Path
    ):
        """Recovering a deleted hook increments retry_count, stays in failures."""
        # Empty registry
        reg = HookRegistry()
        save(reg, hooks_yaml)

        # Log a failure for a hook that no longer exists
        log_failure(
            hook_id="hook-999",
            trigger_tool="trigger_a",
            target_tool="target_b",
            server="srv",
            error="original error",
            source_result="{}",
            path=failures_yaml,
        )

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.storage._FAILURES_FILE", failures_yaml),
            patch("server.tools.recovery.post_hook", new_callable=AsyncMock) as mock_post,
        ):
            result_str = await hooks_recover(hook_id="hook-999")

        data = json.loads(result_str)
        assert data["retried"] == 1
        assert data["succeeded"] == 0
        assert data["still_failed"] == 1
        # post_hook should NOT have been called since the hook is deleted
        mock_post.assert_not_called()
