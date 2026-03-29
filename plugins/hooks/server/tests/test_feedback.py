"""Tests for feedback writeback mechanism."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from server.lib.http_client import FireResult
from server.lib.models import Hook, HookRegistry
from server.lib.storage import save
from server.lib.template import _resolve_path
from server.tools.fire import hooks_fire
from server.tools.registry import hooks_register


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
    param_mapping: dict | None = None,
    feedback_mapping: dict | None = None,
    feedback_tool: str | None = None,
) -> Hook:
    return Hook(
        id=hook_id,
        trigger_tool=trigger,
        target_tool=target,
        server=server,
        blocking=blocking,
        param_mapping=param_mapping or {},
        feedback_mapping=feedback_mapping or {},
        feedback_tool=feedback_tool,
    )


# ── Test: dot-path resolution from mock results ─────────────────────────────


class TestFeedbackMappingResolution:
    def test_resolve_simple_path(self):
        data = {"task_id": "12345", "url": "https://example.com"}
        assert _resolve_path(data, "task_id") == "12345"

    def test_resolve_nested_path(self):
        data = {"result": {"external": {"id": "abc-123"}}}
        assert _resolve_path(data, "result.external.id") == "abc-123"

    def test_resolve_missing_path_returns_none(self):
        data = {"task_id": "12345"}
        assert _resolve_path(data, "nonexistent.path") is None

    def test_resolve_list_index(self):
        data = {"items": [{"name": "first"}, {"name": "second"}]}
        assert _resolve_path(data, "items.1.name") == "second"


# ── Test: feedback only fires on success ─────────────────────────────────────


class TestFeedbackOnlyOnSuccess:
    @pytest.mark.asyncio
    async def test_feedback_skipped_on_hook_failure(self, hooks_yaml: Path):
        """Feedback writeback should not fire when the blocking hook fails."""
        hook = _hook(
            "hook-001", "todo_complete", "todoist_complete", "todoist",
            blocking=True,
            feedback_mapping={"task_id": "todoist_task_id"},
            feedback_tool="todo_update",
        )
        reg = _make_registry(
            [hook],
            servers={
                "todoist": {"url": "http://localhost:19106"},
                "proj": {"url": "http://localhost:19102"},
            },
        )
        save(reg, hooks_yaml)

        failed_result = FireResult(hook_id="hook-001", status_code=500, error="server error", result=None)

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.tools.fire.post_hook", new_callable=AsyncMock, return_value=failed_result) as mock_post,
            patch("server.tools.fire._load_proj_config", return_value={}),
        ):
            raw = await hooks_fire("todo_complete", json.dumps({"todo_id": "t-001"}))
            result = json.loads(raw)

        # The hook fired but failed — no feedback should have been attempted
        assert result["hooks_fired"] == 1
        assert len(result["errors"]) == 1
        # post_hook called only once (for the hook itself, not for feedback)
        assert mock_post.call_count == 1

    @pytest.mark.asyncio
    async def test_feedback_fires_on_success(self, hooks_yaml: Path):
        """Feedback writeback should fire when the blocking hook succeeds."""
        hook = _hook(
            "hook-001", "todo_complete", "todoist_complete", "todoist",
            blocking=True,
            feedback_mapping={"task_id": "todoist_task_id"},
            feedback_tool="todo_update",
        )
        reg = _make_registry(
            [hook],
            servers={
                "todoist": {"url": "http://localhost:19106"},
                "proj": {"url": "http://localhost:19102"},
            },
        )
        save(reg, hooks_yaml)

        hook_result = FireResult(
            hook_id="hook-001", status_code=200, error=None,
            result=json.dumps({"task_id": "ext-999"}),
        )
        feedback_result = FireResult(hook_id="hook-001-feedback", status_code=200, error=None, result=None)

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch(
                "server.tools.fire.post_hook",
                new_callable=AsyncMock,
                side_effect=[hook_result, feedback_result],
            ) as mock_post,
            patch("server.tools.fire._load_proj_config", return_value={}),
        ):
            raw = await hooks_fire("todo_complete", json.dumps({"todo_id": "t-001"}))
            result = json.loads(raw)

        # Hook succeeded + feedback fired
        assert result["hooks_fired"] == 1
        assert result["errors"] == []
        assert len(result.get("feedback", [])) == 1
        assert result["feedback"][0]["ok"] is True

        # post_hook called twice: once for hook, once for feedback
        assert mock_post.call_count == 2
        fb_call = mock_post.call_args_list[1]
        assert fb_call.kwargs["target_tool"] == "todo_update"
        assert fb_call.kwargs["params"]["todoist_task_id"] == "ext-999"
        assert fb_call.kwargs["params"]["todo_id"] == "t-001"


# ── Test: feedback requires blocking ─────────────────────────────────────────


class TestFeedbackOnlyOnBlocking:
    def test_registration_rejects_feedback_on_non_blocking(self, hooks_yaml: Path):
        """hooks_register should reject feedback_mapping on non-blocking hooks."""
        with patch("server.lib.storage._HOOKS_FILE", hooks_yaml):
            raw = hooks_register(
                trigger_tool="todo_complete",
                target_tool="todoist_complete",
                server="todoist",
                blocking=False,
                feedback_mapping='{"task_id": "todoist_task_id"}',
                feedback_tool="todo_update",
            )
        result = json.loads(raw)
        assert "Error" in result["result"]
        assert "blocking" in result["result"].lower()
        assert result["hook_id"] is None

    def test_registration_accepts_feedback_on_blocking(self, hooks_yaml: Path):
        """hooks_register should accept feedback_mapping on blocking hooks."""
        with patch("server.lib.storage._HOOKS_FILE", hooks_yaml):
            raw = hooks_register(
                trigger_tool="todo_complete",
                target_tool="todoist_complete",
                server="todoist",
                blocking=True,
                feedback_mapping='{"task_id": "todoist_task_id"}',
                feedback_tool="todo_update",
            )
        result = json.loads(raw)
        assert "Error" not in result["result"]
        assert result["hook_id"] is not None


# ── Test: serialization roundtrip ────────────────────────────────────────────


class TestFeedbackMappingSerialization:
    def test_to_dict_includes_feedback_fields(self):
        h = Hook(
            id="hook-001",
            trigger_tool="a",
            target_tool="b",
            server="s",
            blocking=True,
            feedback_mapping={"task_id": "todoist_task_id"},
            feedback_tool="todo_update",
        )
        d = h.to_dict()
        assert d["feedback_mapping"] == {"task_id": "todoist_task_id"}
        assert d["feedback_tool"] == "todo_update"

    def test_to_dict_omits_empty_feedback(self):
        h = Hook(id="hook-001", trigger_tool="a", target_tool="b", server="s")
        d = h.to_dict()
        assert "feedback_mapping" not in d
        assert "feedback_tool" not in d

    def test_from_dict_round_trip(self):
        original = Hook(
            id="hook-001",
            trigger_tool="a",
            target_tool="b",
            server="s",
            blocking=True,
            feedback_mapping={"ext_id": "local_id", "url": "external_url"},
            feedback_tool="todo_update",
        )
        d = original.to_dict()
        restored = Hook.from_dict(d)
        assert restored.feedback_mapping == original.feedback_mapping
        assert restored.feedback_tool == original.feedback_tool

    def test_from_dict_defaults_when_missing(self):
        h = Hook.from_dict({"id": "hook-001", "trigger_tool": "a", "target_tool": "b", "server": "s"})
        assert h.feedback_mapping == {}
        assert h.feedback_tool is None
