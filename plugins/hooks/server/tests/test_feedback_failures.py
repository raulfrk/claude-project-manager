"""Tests for feedback writeback failure logging (todo-408)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch, call

import pytest

from server.lib.http_client import FireResult
from server.lib.models import Hook, HookRegistry
from server.lib.storage import save
from server.tools.fire import hooks_fire


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_registry(hooks: list[Hook], servers: dict | None = None, settings: dict | None = None):
    return HookRegistry(
        hooks=hooks,
        servers=servers or {},
        settings=settings or {},
    )


def _hook_with_feedback(hook_id: str = "hook-001") -> Hook:
    return Hook(
        id=hook_id,
        trigger_tool="todo_complete",
        target_tool="todoist_complete",
        server="todoist",
        blocking=True,
        param_mapping={},
        feedback_mapping={"task_id": "todoist_task_id"},
        feedback_tool="todo_update",
    )


def _servers():
    return {
        "todoist": {"url": "http://localhost:19106"},
        "proj": {"url": "http://localhost:19102"},
    }


def _success_hook_result(hook_id: str = "hook-001") -> FireResult:
    return FireResult(
        hook_id=hook_id,
        status_code=200,
        error=None,
        result=json.dumps({"task_id": "ext-999"}),
    )


# ── Test: fb_result.ok=False → log_failure + errors ─────────────────────────


class TestFeedbackWritebackFailure:
    @pytest.mark.asyncio
    async def test_feedback_failure_logs_and_surfaces_error(self, hooks_yaml: Path):
        """When fb_result.ok is False, log_failure is called and error is in errors list."""
        hook = _hook_with_feedback()
        reg = _make_registry([hook], servers=_servers())
        save(reg, hooks_yaml)

        hook_result = _success_hook_result()
        fb_fail = FireResult(
            hook_id="hook-001-feedback",
            status_code=500,
            error="internal server error",
            result=None,
        )

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch(
                "server.tools.fire.post_hook",
                new_callable=AsyncMock,
                side_effect=[hook_result, fb_fail],
            ),
            patch("server.tools.fire._load_proj_config", return_value={}),
            patch("server.tools.fire._resolve_server_url", return_value="http://localhost:9999"),
            patch("server.tools.fire.storage.log_failure") as mock_log_failure,
        ):
            raw = await hooks_fire("todo_complete", json.dumps({"todo_id": "t-001"}))
            result = json.loads(raw)

        # Feedback failure should appear in errors
        fb_errors = [e for e in result["errors"] if "feedback" in e["hook_id"]]
        assert len(fb_errors) == 1
        assert fb_errors[0]["hook_id"] == "hook-001-feedback"
        assert fb_errors[0]["error"] == "internal server error"
        assert fb_errors[0]["target_tool"] == "todo_update"

        # log_failure should have been called for the feedback failure
        mock_log_failure.assert_called_once_with(
            hook_id="hook-001-feedback",
            trigger_tool="todo_complete",
            target_tool="todo_update",
            server="todoist",
            error="internal server error",
            source_result=json.dumps({"todo_id": "t-001"}),
        )

    @pytest.mark.asyncio
    async def test_feedback_failure_error_none_falls_back_to_status_code(self, hooks_yaml: Path):
        """When fb_result.error is None but ok=False, error message uses HTTP status code."""
        hook = _hook_with_feedback()
        reg = _make_registry([hook], servers=_servers())
        save(reg, hooks_yaml)

        hook_result = _success_hook_result()
        # error=None but status_code >= 400 makes ok=False
        fb_fail = FireResult(
            hook_id="hook-001-feedback",
            status_code=502,
            error=None,
            result=None,
        )

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch(
                "server.tools.fire.post_hook",
                new_callable=AsyncMock,
                side_effect=[hook_result, fb_fail],
            ),
            patch("server.tools.fire._load_proj_config", return_value={}),
            patch("server.tools.fire._resolve_server_url", return_value="http://localhost:9999"),
            patch("server.tools.fire.storage.log_failure") as mock_log_failure,
        ):
            raw = await hooks_fire("todo_complete", json.dumps({"todo_id": "t-001"}))
            result = json.loads(raw)

        fb_errors = [e for e in result["errors"] if "feedback" in e["hook_id"]]
        assert len(fb_errors) == 1
        assert fb_errors[0]["error"] == "HTTP 502"

        mock_log_failure.assert_called_once()
        assert mock_log_failure.call_args.kwargs["error"] == "HTTP 502"


# ── Test: post_hook raises exception → caught, logged, appended ──────────────


class TestFeedbackWritebackException:
    @pytest.mark.asyncio
    async def test_exception_caught_and_logged(self, hooks_yaml: Path):
        """When post_hook raises during feedback, the exception is caught and logged."""
        hook = _hook_with_feedback()
        reg = _make_registry([hook], servers=_servers())
        save(reg, hooks_yaml)

        hook_result = _success_hook_result()

        async def _side_effect(**kwargs):
            if "feedback" in kwargs.get("hook_id", ""):
                raise ConnectionError("connection refused")
            return hook_result

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.tools.fire.post_hook", new_callable=AsyncMock, side_effect=_side_effect),
            patch("server.tools.fire._load_proj_config", return_value={}),
            patch("server.tools.fire._resolve_server_url", return_value="http://localhost:9999"),
            patch("server.tools.fire.storage.log_failure") as mock_log_failure,
        ):
            raw = await hooks_fire("todo_complete", json.dumps({"todo_id": "t-001"}))
            result = json.loads(raw)

        # Error should be in errors list
        fb_errors = [e for e in result["errors"] if "feedback" in e["hook_id"]]
        assert len(fb_errors) == 1
        assert "feedback writeback exception" in fb_errors[0]["error"]
        assert "connection refused" in fb_errors[0]["error"]

        # log_failure should have been called
        mock_log_failure.assert_called_once()
        call_kwargs = mock_log_failure.call_args.kwargs
        assert call_kwargs["hook_id"] == "hook-001-feedback"
        assert "connection refused" in call_kwargs["error"]

        # Feedback results should also show the failure
        fb = result.get("feedback", [])
        assert len(fb) == 1
        assert fb[0]["ok"] is False
        assert "connection refused" in fb[0]["error"]


# ── Test: success path unchanged → log_failure NOT called ────────────────────


class TestFeedbackSuccessUnchanged:
    @pytest.mark.asyncio
    async def test_success_does_not_call_log_failure(self, hooks_yaml: Path):
        """On successful feedback writeback, log_failure should not be called."""
        hook = _hook_with_feedback()
        reg = _make_registry([hook], servers=_servers())
        save(reg, hooks_yaml)

        hook_result = _success_hook_result()
        fb_ok = FireResult(hook_id="hook-001-feedback", status_code=200, error=None, result=None)

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch(
                "server.tools.fire.post_hook",
                new_callable=AsyncMock,
                side_effect=[hook_result, fb_ok],
            ),
            patch("server.tools.fire._load_proj_config", return_value={}),
            patch("server.tools.fire._resolve_server_url", return_value="http://localhost:9999"),
            patch("server.tools.fire.storage.log_failure") as mock_log_failure,
        ):
            raw = await hooks_fire("todo_complete", json.dumps({"todo_id": "t-001"}))
            result = json.loads(raw)

        assert result["errors"] == []
        assert len(result.get("feedback", [])) == 1
        assert result["feedback"][0]["ok"] is True
        mock_log_failure.assert_not_called()
