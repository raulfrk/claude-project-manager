"""Tests filling coverage gaps identified during the hooks plugin audit.

Covers:
- _get_max_depth edge cases (fire.py)
- _resolve_server_url Unix mode with empty file content
- _fire_single server URL fallback to hooks.yaml servers map
- hooks_fire with empty source dict (no merge)
- Batch feedback writeback with [*] pattern
- Batch feedback partial failures and exceptions
- Single-value feedback HTTP failure logging
- hooks_invocations filtering (target_tool, type, limit clamping)
- hooks_recover _retry_entry when hook not in registry
- _resolve_path walking into scalar (template.py)
- _parse_verification_response non-dict JSON
- Hook.update_from with condition set to None explicitly
- HookRegistry.from_dict with hooks containing non-standard IDs
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import yaml

from server.lib.http_client import FireResult
from server.lib.models import Hook, HookRegistry
from server.lib.storage import (
    load_failures,
    log_failure,
    log_invocation,
    save,
)
from server.lib.template import _resolve_path
from server.tools.fire import (
    _get_max_depth,
    _parse_verification_response,
    hooks_fire,
)
from server.tools.invocations import hooks_invocations
from server.tools.recovery import hooks_recover

# ── _get_max_depth edge cases ──────────────────────────────────────────────────


class TestGetMaxDepth:
    def test_reads_from_settings(self, hooks_yaml: Path):
        """max_depth is read from hooks.yaml settings when present."""
        reg = HookRegistry(settings={"max_depth": 7})
        save(reg, hooks_yaml)
        with patch("server.lib.storage._HOOKS_FILE", hooks_yaml):
            assert _get_max_depth() == 7

    def test_defaults_when_missing(self, hooks_yaml: Path):
        """Falls back to DEFAULT_MAX_DEPTH when settings has no max_depth."""
        reg = HookRegistry(settings={})
        save(reg, hooks_yaml)
        with patch("server.lib.storage._HOOKS_FILE", hooks_yaml):
            assert _get_max_depth() == 3

    def test_ignores_zero(self, hooks_yaml: Path):
        """max_depth=0 is not positive, so defaults to 3."""
        reg = HookRegistry(settings={"max_depth": 0})
        save(reg, hooks_yaml)
        with patch("server.lib.storage._HOOKS_FILE", hooks_yaml):
            assert _get_max_depth() == 3

    def test_ignores_negative(self, hooks_yaml: Path):
        """Negative max_depth defaults to 3."""
        reg = HookRegistry(settings={"max_depth": -1})
        save(reg, hooks_yaml)
        with patch("server.lib.storage._HOOKS_FILE", hooks_yaml):
            assert _get_max_depth() == 3

    def test_ignores_non_int(self, hooks_yaml: Path):
        """Non-int max_depth (e.g., string) defaults to 3."""
        reg = HookRegistry(settings={"max_depth": "five"})
        save(reg, hooks_yaml)
        with patch("server.lib.storage._HOOKS_FILE", hooks_yaml):
            assert _get_max_depth() == 3

    def test_settings_not_a_dict(self, hooks_yaml: Path):
        """When settings is not a dict (e.g., after bad YAML), defaults to 3."""
        # Write raw YAML with settings as a list
        hooks_yaml.write_text(yaml.dump({"hooks": [], "settings": [1, 2]}))
        with patch("server.lib.storage._HOOKS_FILE", hooks_yaml):
            # HookRegistry.from_dict ignores non-dict settings -> empty dict
            assert _get_max_depth() == 3


# ── _resolve_server_url edge cases ──────────────────────────────────────────


class TestResolveServerUrlEdge:
    def test_unix_mode_empty_registry_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Empty socket registry file falls back to glob then server name."""
        from unittest.mock import patch

        from server.tools.fire import _resolve_server_url

        registry_file = tmp_path / "proj"
        registry_file.write_text("")
        monkeypatch.setenv("HOOK_TRANSPORT", "unix")
        monkeypatch.setattr("server.tools.fire._SOCKET_REGISTRY_DIR", tmp_path)
        with patch("server.tools.fire.glob.glob", return_value=[]):
            result = _resolve_server_url("proj", 19100)
        assert result == "proj"  # empty file + no glob matches -> fallback

    def test_unix_mode_whitespace_only_registry_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Whitespace-only socket registry file falls back to glob then server name."""
        from unittest.mock import patch

        from server.tools.fire import _resolve_server_url

        registry_file = tmp_path / "proj"
        registry_file.write_text("   \n  ")
        monkeypatch.setenv("HOOK_TRANSPORT", "unix")
        monkeypatch.setattr("server.tools.fire._SOCKET_REGISTRY_DIR", tmp_path)
        with patch("server.tools.fire.glob.glob", return_value=[]):
            result = _resolve_server_url("proj", 19100)
        assert result == "proj"


# ── _fire_single server URL fallback ────────────────────────────────────────


class TestFireSingleServerFallback:
    @pytest.mark.asyncio
    async def test_falls_back_to_hooks_yaml_server_url(self, hooks_yaml: Path):
        """When socket registry falls back to raw name, _fire_single uses hooks.yaml servers."""
        hook = Hook(
            id="h-001",
            trigger_tool="trig",
            target_tool="tgt",
            server="my-server",
            param_mapping={},
            blocking=True,
        )
        reg = HookRegistry(
            hooks=[hook],
            servers={"my-server": {"url": "http://127.0.0.1:19999/hook"}},
        )
        save(reg, hooks_yaml)

        captured_urls: list[str] = []

        async def mock_post_hook(*, hook_id, url, target_tool, params):
            captured_urls.append(url)
            return FireResult(hook_id=hook_id, status_code=200, body="ok")

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            # _resolve_server_url returns the raw server name (fallback)
            patch("server.tools.fire._resolve_server_url", return_value="my-server"),
            patch("server.tools.fire.post_hook", side_effect=mock_post_hook),
        ):
            result = await hooks_fire("trig", source_result="{}", depth=0)

        data = json.loads(result)
        assert data["hooks_fired"] == 1
        # Should have used the URL from hooks.yaml servers
        assert captured_urls[0] == "http://127.0.0.1:19999/hook"


# ── hooks_fire with empty source ────────────────────────────────────────────


class TestHooksFireEmptySource:
    @pytest.mark.asyncio
    async def test_empty_source_no_condition_merge(self, hooks_yaml: Path, proj_yaml: Path):
        """Empty source_result '{}' does not attempt field injection."""
        hook = Hook(
            id="h-001",
            trigger_tool="trig",
            target_tool="tgt",
            server="srv",
        )
        reg = HookRegistry(hooks=[hook])
        save(reg, hooks_yaml)
        proj_yaml.write_text("")

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.conditions._PROJ_CONFIG_PATH", proj_yaml),
            patch(
                "server.tools.fire._fire_single",
                new_callable=AsyncMock,
                return_value=FireResult(hook_id="h-001", status_code=200, body="ok"),
            ),
        ):
            result = await hooks_fire("trig", source_result="{}", depth=0)

        data = json.loads(result)
        assert data["non_blocking_dispatched"] == 1


# ── Batch feedback writeback ────────────────────────────────────────────────


class TestBatchFeedbackWriteback:
    @pytest.mark.asyncio
    async def test_batch_feedback_iterates_over_created(
        self, hooks_yaml: Path, failures_yaml: Path
    ):
        """Batch feedback with [*] pattern iterates over source.created and result array."""
        hook_data = {
            "hooks": [
                {
                    "id": "h-batch",
                    "trigger_tool": "todo_batch_add_children",
                    "target_tool": "todoist_add_tasks",
                    "server": "todoist",
                    "blocking": True,
                    "param_mapping": {},
                    "feedback_mapping": {"successes[*].id": "todoist_task_id"},
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
            # Primary hook returns batch results
            return FireResult(
                hook_id=hook_id,
                status_code=200,
                body="ok",
                result=json.dumps(
                    {"successes": [{"id": "tid-1"}, {"id": "tid-2"}, {"id": "tid-3"}]}
                ),
            )

        source = {
            "created": [
                {"id": "child-1", "title": "A"},
                {"id": "child-2", "title": "B"},
                {"id": "child-3", "title": "C"},
            ],
            "project_name": "test-proj",
        }

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.storage._FAILURES_FILE", failures_yaml),
            patch("server.tools.fire._resolve_server_url", return_value="unix:///tmp/t.sock"),
            patch("server.tools.fire.post_hook", side_effect=mock_post_hook),
        ):
            result = await hooks_fire(
                "todo_batch_add_children",
                source_result=json.dumps(source),
                depth=0,
            )

        data = json.loads(result)
        assert "feedback" in data
        assert len(data["feedback"]) == 3
        # Verify each child got its own feedback call
        assert len(feedback_calls) == 3
        assert feedback_calls[0]["params"]["todoist_task_id"] == "tid-1"
        assert feedback_calls[0]["params"]["todo_id"] == "child-1"
        assert feedback_calls[0]["params"]["project_name"] == "test-proj"
        assert feedback_calls[1]["params"]["todoist_task_id"] == "tid-2"
        assert feedback_calls[2]["params"]["todoist_task_id"] == "tid-3"

    @pytest.mark.asyncio
    async def test_batch_feedback_partial_result(self, hooks_yaml: Path, failures_yaml: Path):
        """Batch feedback handles fewer results than children (partial failure)."""
        hook_data = {
            "hooks": [
                {
                    "id": "h-batch",
                    "trigger_tool": "batch_add",
                    "target_tool": "ext_add",
                    "server": "ext",
                    "blocking": True,
                    "param_mapping": {},
                    "feedback_mapping": {"results[*].ext_id": "ext_id"},
                    "feedback_tool": "todo_update",
                }
            ]
        }
        hooks_yaml.write_text(yaml.dump(hook_data))

        feedback_calls: list[dict] = []

        async def mock_post_hook(*, hook_id, url, target_tool, params):
            if target_tool == "todo_update":
                feedback_calls.append(params)
                return FireResult(hook_id=hook_id, status_code=200, body="ok")
            # Only 1 result for 3 children
            return FireResult(
                hook_id=hook_id,
                status_code=200,
                body="ok",
                result=json.dumps({"results": [{"ext_id": "e-1"}]}),
            )

        source = {
            "created": [
                {"id": "c-1"},
                {"id": "c-2"},
                {"id": "c-3"},
            ],
        }

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.storage._FAILURES_FILE", failures_yaml),
            patch("server.tools.fire._resolve_server_url", return_value="unix:///tmp/t.sock"),
            patch("server.tools.fire.post_hook", side_effect=mock_post_hook),
        ):
            result = await hooks_fire("batch_add", source_result=json.dumps(source), depth=0)

        json.loads(result)
        # Only 1 feedback call (fewer results than children)
        assert len(feedback_calls) == 1
        assert feedback_calls[0]["ext_id"] == "e-1"
        assert feedback_calls[0]["todo_id"] == "c-1"

    @pytest.mark.asyncio
    async def test_batch_feedback_skips_children_without_id(
        self, hooks_yaml: Path, failures_yaml: Path
    ):
        """Batch feedback skips created entries missing 'id' field."""
        hook_data = {
            "hooks": [
                {
                    "id": "h-batch",
                    "trigger_tool": "batch_add",
                    "target_tool": "ext_add",
                    "server": "ext",
                    "blocking": True,
                    "param_mapping": {},
                    "feedback_mapping": {"items[*].eid": "ext_id"},
                    "feedback_tool": "todo_update",
                }
            ]
        }
        hooks_yaml.write_text(yaml.dump(hook_data))

        feedback_calls: list[dict] = []

        async def mock_post_hook(*, hook_id, url, target_tool, params):
            if target_tool == "todo_update":
                feedback_calls.append(params)
                return FireResult(hook_id=hook_id, status_code=200, body="ok")
            return FireResult(
                hook_id=hook_id,
                status_code=200,
                body="ok",
                result=json.dumps({"items": [{"eid": "e1"}, {"eid": "e2"}]}),
            )

        source = {
            "created": [
                {"id": "c-1"},  # Has id
                {"title": "no-id"},  # Missing id field
            ],
        }

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.storage._FAILURES_FILE", failures_yaml),
            patch("server.tools.fire._resolve_server_url", return_value="unix:///tmp/t.sock"),
            patch("server.tools.fire.post_hook", side_effect=mock_post_hook),
        ):
            await hooks_fire("batch_add", source_result=json.dumps(source), depth=0)

        # Only child-1 got feedback, child without id was skipped
        assert len(feedback_calls) == 1
        assert feedback_calls[0]["todo_id"] == "c-1"

    @pytest.mark.asyncio
    async def test_batch_feedback_exception_per_item(self, hooks_yaml: Path, failures_yaml: Path):
        """Exception during a batch feedback item is caught and logged."""
        hook_data = {
            "hooks": [
                {
                    "id": "h-batch",
                    "trigger_tool": "batch_add",
                    "target_tool": "ext_add",
                    "server": "ext",
                    "blocking": True,
                    "param_mapping": {},
                    "feedback_mapping": {"items[*].eid": "ext_id"},
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
                raise ConnectionError("server gone")
            return FireResult(
                hook_id=hook_id,
                status_code=200,
                body="ok",
                result=json.dumps({"items": [{"eid": "e1"}]}),
            )

        source = {"created": [{"id": "c-1"}]}

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.storage._FAILURES_FILE", failures_yaml),
            patch("server.tools.fire._resolve_server_url", return_value="unix:///tmp/t.sock"),
            patch("server.tools.fire.post_hook", side_effect=mock_post_hook),
        ):
            result = await hooks_fire("batch_add", source_result=json.dumps(source), depth=0)

        data = json.loads(result)
        assert "feedback" in data
        assert data["feedback"][0]["ok"] is False
        # Error should be in errors list
        assert any("feedback" in str(e.get("hook_id", "")) for e in data["errors"])

    @pytest.mark.asyncio
    async def test_batch_feedback_http_failure_logged(self, hooks_yaml: Path, failures_yaml: Path):
        """HTTP failure during batch feedback is logged."""
        hook_data = {
            "hooks": [
                {
                    "id": "h-batch",
                    "trigger_tool": "batch_add",
                    "target_tool": "ext_add",
                    "server": "ext",
                    "blocking": True,
                    "param_mapping": {},
                    "feedback_mapping": {"items[*].eid": "ext_id"},
                    "feedback_tool": "todo_update",
                }
            ]
        }
        hooks_yaml.write_text(yaml.dump(hook_data))

        async def mock_post_hook(*, hook_id, url, target_tool, params):
            if target_tool == "todo_update":
                return FireResult(hook_id=hook_id, status_code=500, body="err", error="HTTP 500")
            return FireResult(
                hook_id=hook_id,
                status_code=200,
                body="ok",
                result=json.dumps({"items": [{"eid": "e1"}]}),
            )

        source = {"created": [{"id": "c-1"}]}

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.storage._FAILURES_FILE", failures_yaml),
            patch("server.tools.fire._resolve_server_url", return_value="unix:///tmp/t.sock"),
            patch("server.tools.fire.post_hook", side_effect=mock_post_hook),
        ):
            result = await hooks_fire("batch_add", source_result=json.dumps(source), depth=0)

        data = json.loads(result)
        assert "feedback" in data
        assert data["feedback"][0]["ok"] is False
        assert any("feedback" in str(e.get("hook_id", "")) for e in data["errors"])

    @pytest.mark.asyncio
    async def test_batch_feedback_skips_non_list_source_created(
        self, hooks_yaml: Path, failures_yaml: Path
    ):
        """Batch feedback is skipped when source.created is not a list."""
        hook_data = {
            "hooks": [
                {
                    "id": "h-batch",
                    "trigger_tool": "batch_add",
                    "target_tool": "ext_add",
                    "server": "ext",
                    "blocking": True,
                    "param_mapping": {},
                    "feedback_mapping": {"items[*].eid": "ext_id"},
                    "feedback_tool": "todo_update",
                }
            ]
        }
        hooks_yaml.write_text(yaml.dump(hook_data))

        async def mock_post_hook(*, hook_id, url, target_tool, params):
            return FireResult(
                hook_id=hook_id,
                status_code=200,
                body="ok",
                result=json.dumps({"items": [{"eid": "e1"}]}),
            )

        # source.created is a string, not a list
        source = {"created": "not-a-list"}

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.storage._FAILURES_FILE", failures_yaml),
            patch("server.tools.fire._resolve_server_url", return_value="unix:///tmp/t.sock"),
            patch("server.tools.fire.post_hook", side_effect=mock_post_hook),
        ):
            result = await hooks_fire("batch_add", source_result=json.dumps(source), depth=0)

        data = json.loads(result)
        # No feedback because created is not a list
        assert "feedback" not in data


# ── Single-value feedback HTTP failure ─────────────────────────────────────


class TestSingleValueFeedbackFailure:
    @pytest.mark.asyncio
    async def test_feedback_http_failure_logged(self, hooks_yaml: Path, failures_yaml: Path):
        """Single-value feedback HTTP failure is logged and reported."""
        hook_data = {
            "hooks": [
                {
                    "id": "h-fb",
                    "trigger_tool": "todo_add",
                    "target_tool": "todoist_add_tasks",
                    "server": "todoist",
                    "blocking": True,
                    "param_mapping": {},
                    "feedback_mapping": {"task_id": "todoist_task_id"},
                    "feedback_tool": "todo_update",
                }
            ]
        }
        hooks_yaml.write_text(yaml.dump(hook_data))

        async def mock_post_hook(*, hook_id, url, target_tool, params):
            if target_tool == "todo_update":
                return FireResult(hook_id=hook_id, status_code=500, body="err", error="HTTP 500")
            return FireResult(
                hook_id=hook_id,
                status_code=200,
                body='{"task_id": "t1"}',
                result='{"task_id": "t1"}',
            )

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.storage._FAILURES_FILE", failures_yaml),
            patch("server.tools.fire._resolve_server_url", return_value="unix:///tmp/t.sock"),
            patch("server.tools.fire.post_hook", side_effect=mock_post_hook),
        ):
            result = await hooks_fire("todo_add", source_result='{"todo_id": "t1"}', depth=0)

        data = json.loads(result)
        assert "feedback" in data
        assert data["feedback"][0]["ok"] is False
        # Failure logged as error
        feedback_errors = [e for e in data["errors"] if "feedback" in str(e.get("hook_id", ""))]
        assert len(feedback_errors) == 1


# ── _parse_verification_response edge cases ─────────────────────────────────


class TestParseVerificationResponseEdge:
    def test_non_dict_json(self):
        """JSON that parses to a list (not dict) is treated as fail."""
        status, details = _parse_verification_response("[1, 2, 3]")
        assert status == "fail"
        assert "[1, 2, 3]" in details

    def test_dict_without_status_key(self):
        """Dict without 'status' key is treated as fail with raw string."""
        status, _details = _parse_verification_response('{"result": "ok"}')
        assert status == "fail"

    def test_status_with_empty_details(self):
        """Missing details field defaults to empty string."""
        status, details = _parse_verification_response('{"status": "pass"}')
        assert status == "pass"
        assert details == ""

    def test_non_string_status_coerced(self):
        """Non-string status is coerced to string."""
        status, details = _parse_verification_response('{"status": 42, "details": "d"}')
        assert status == "42"
        assert details == "d"


# ── hooks_invocations tests ─────────────────────────────────────────────────


class TestHooksInvocations:
    def test_filter_by_target_tool(self, tmp_path: Path, failures_yaml: Path):
        """Filtering by target_tool returns only matching entries."""
        inv_path = tmp_path / "inv.yaml"
        log_invocation(
            hook_id="h-1", trigger_tool="t", target_tool="alpha", server="s", path=inv_path
        )
        log_invocation(
            hook_id="h-2", trigger_tool="t", target_tool="beta", server="s", path=inv_path
        )

        with (
            patch("server.lib.storage._INVOCATIONS_FILE", inv_path),
            patch("server.lib.storage._FAILURES_FILE", failures_yaml),
        ):
            result = hooks_invocations(target_tool="alpha")

        data = json.loads(result)
        assert data["total"] == 1
        assert data["entries"][0]["hook_id"] == "h-1"

    def test_type_invocation_only(self, tmp_path: Path, failures_yaml: Path):
        """type='invocation' excludes failures."""
        inv_path = tmp_path / "inv.yaml"
        log_invocation(hook_id="h-1", trigger_tool="t", target_tool="u", server="s", path=inv_path)
        log_failure(
            hook_id="h-2",
            trigger_tool="t",
            target_tool="u",
            server="s",
            error="boom",
            path=failures_yaml,
        )

        with (
            patch("server.lib.storage._INVOCATIONS_FILE", inv_path),
            patch("server.lib.storage._FAILURES_FILE", failures_yaml),
        ):
            result = hooks_invocations(type="invocation")

        data = json.loads(result)
        assert data["total"] == 1
        assert all(e["_type"] == "invocation" for e in data["entries"])

    def test_type_failure_only(self, tmp_path: Path, failures_yaml: Path):
        """type='failure' excludes invocations."""
        inv_path = tmp_path / "inv.yaml"
        log_invocation(hook_id="h-1", trigger_tool="t", target_tool="u", server="s", path=inv_path)
        log_failure(
            hook_id="h-2",
            trigger_tool="t",
            target_tool="u",
            server="s",
            error="boom",
            path=failures_yaml,
        )

        with (
            patch("server.lib.storage._INVOCATIONS_FILE", inv_path),
            patch("server.lib.storage._FAILURES_FILE", failures_yaml),
        ):
            result = hooks_invocations(type="failure")

        data = json.loads(result)
        assert data["total"] == 1
        assert all(e["_type"] == "failure" for e in data["entries"])

    def test_limit_clamped_at_200(self, tmp_path: Path, failures_yaml: Path):
        """Limit is clamped to max 200."""
        inv_path = tmp_path / "inv.yaml"
        with (
            patch("server.lib.storage._INVOCATIONS_FILE", inv_path),
            patch("server.lib.storage._FAILURES_FILE", failures_yaml),
        ):
            result = hooks_invocations(limit=999)

        data = json.loads(result)
        assert data["limit"] == 200

    def test_combined_filter_hook_id_and_type(self, tmp_path: Path, failures_yaml: Path):
        """Combined hook_id + type filter returns only matching entries."""
        inv_path = tmp_path / "inv.yaml"
        log_invocation(hook_id="h-1", trigger_tool="t", target_tool="u", server="s", path=inv_path)
        log_failure(
            hook_id="h-1",
            trigger_tool="t",
            target_tool="u",
            server="s",
            error="err",
            path=failures_yaml,
        )

        with (
            patch("server.lib.storage._INVOCATIONS_FILE", inv_path),
            patch("server.lib.storage._FAILURES_FILE", failures_yaml),
        ):
            result = hooks_invocations(hook_id="h-1", type="failure")

        data = json.loads(result)
        assert data["total"] == 1
        assert data["entries"][0]["_type"] == "failure"


# ── hooks_recover edge cases ────────────────────────────────────────────────


class TestHooksRecoverEdge:
    @pytest.mark.asyncio
    async def test_retry_when_hook_not_in_registry(self, hooks_yaml: Path, failures_yaml: Path):
        """Hook no longer in registry: retry returns False without calling post_hook."""
        # Save empty registry (no hooks)
        save(HookRegistry(), hooks_yaml)
        # Add a failure entry for a hook that no longer exists
        log_failure(
            hook_id="hook-999",
            trigger_tool="t",
            target_tool="u",
            server="s",
            error="orig-error",
            source_result='{"key": "val"}',
            path=failures_yaml,
        )

        mock_post_hook = AsyncMock()

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.storage._FAILURES_FILE", failures_yaml),
            patch("server.tools.recovery.post_hook", side_effect=mock_post_hook),
        ):
            result = await hooks_recover(hook_id="hook-999")

        data = json.loads(result)
        assert data["retried"] == 1
        assert data["succeeded"] == 0
        assert data["still_failed"] == 1
        mock_post_hook.assert_not_called()

    @pytest.mark.asyncio
    async def test_retry_increments_retry_count_on_failure(
        self, hooks_yaml: Path, failures_yaml: Path
    ):
        """Failed retry increments retry_count and updates timestamp."""
        save(HookRegistry(), hooks_yaml)
        log_failure(
            hook_id="hook-001",
            trigger_tool="t",
            target_tool="u",
            server="s",
            error="err",
            path=failures_yaml,
        )

        async def mock_post_hook(*, hook_id, url, target_tool, params):
            return FireResult(hook_id=hook_id, status_code=500, body="err", error="still bad")

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.storage._FAILURES_FILE", failures_yaml),
            patch("server.tools.recovery.post_hook", side_effect=mock_post_hook),
        ):
            result = await hooks_recover(hook_id="hook-001")

        data = json.loads(result)
        assert data["retried"] == 1
        assert data["succeeded"] == 0
        assert data["still_failed"] == 1

        # Check the failure entry was updated
        entries = load_failures(failures_yaml)
        assert len(entries) == 1
        assert entries[0]["retry_count"] == 1

    @pytest.mark.asyncio
    async def test_retry_invalid_source_result_uses_empty_dict(
        self, hooks_yaml: Path, failures_yaml: Path
    ):
        """Invalid JSON in source_result falls back to empty dict for param resolution."""
        # Hook must exist in registry for retry to proceed
        hook = Hook(id="hook-001", trigger_tool="t", target_tool="u", server="s")
        save(
            HookRegistry(hooks=[hook], servers={"s": {"url": "http://localhost/hook"}}), hooks_yaml
        )
        # Manually write a failure with invalid source_result
        entries = [
            {
                "hook_id": "hook-001",
                "trigger_tool": "t",
                "target_tool": "u",
                "server": "s",
                "error": "err",
                "source_result": "not-valid-json",
            }
        ]
        failures_yaml.write_text(yaml.dump(entries))

        captured_params: list[dict] = []

        async def mock_post_hook(*, hook_id, url, target_tool, params):
            captured_params.append(params)
            return FireResult(hook_id=hook_id, status_code=200, body="ok")

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.storage._FAILURES_FILE", failures_yaml),
            patch("server.tools.recovery.post_hook", side_effect=mock_post_hook),
        ):
            result = await hooks_recover(hook_id="hook-001")

        data = json.loads(result)
        assert data["succeeded"] == 1
        assert captured_params[0] == {}


# ── _resolve_path edge cases (template.py) ──────────────────────────────────


class TestResolvePathEdge:
    def test_walk_into_scalar_value(self):
        """Walking into an int/string/bool returns None (not a container)."""
        assert _resolve_path({"a": 42}, "a.b") is None
        assert _resolve_path({"a": "hello"}, "a.b") is None
        assert _resolve_path({"a": True}, "a.b") is None

    def test_walk_into_none_value(self):
        """Walking into None returns None."""
        assert _resolve_path({"a": None}, "a.b") is None

    def test_walk_list_non_numeric_index(self):
        """Non-numeric segment on a list returns None."""
        assert _resolve_path({"items": [1, 2]}, "items.abc") is None

    def test_walk_list_negative_index_succeeds(self):
        """Negative index on a list works because Python supports list[-1]."""
        result = _resolve_path({"items": ["a", "b", "c"]}, "items.-1")
        # int("-1") = -1, and list[-1] = "c" in Python
        assert result == "c"

    def test_single_segment_path(self):
        """Single-segment path returns the top-level value."""
        assert _resolve_path({"key": "val"}, "key") == "val"

    def test_empty_dict(self):
        """Path into empty dict returns None."""
        assert _resolve_path({}, "anything") is None


# ── Hook model edge cases ───────────────────────────────────────────────────


class TestHookModelEdge:
    def test_update_from_condition_to_none(self):
        """update_from can set condition to None explicitly."""
        h = Hook(
            id="hook-001",
            trigger_tool="a",
            target_tool="b",
            server="s",
            condition="some.flag",
        )
        h.update_from({"condition": None})
        assert h.condition is None

    def test_update_from_feedback_tool_to_none(self):
        """update_from can clear feedback_tool to None."""
        h = Hook(
            id="hook-001",
            trigger_tool="a",
            target_tool="b",
            server="s",
            feedback_tool="old_tool",
        )
        h.update_from({"feedback_tool": None})
        assert h.feedback_tool is None

    def test_update_from_non_dict_feedback_mapping_clears(self):
        """update_from with non-dict feedback_mapping clears it."""
        h = Hook(
            id="hook-001",
            trigger_tool="a",
            target_tool="b",
            server="s",
            feedback_mapping={"old": "val"},
        )
        h.update_from({"feedback_mapping": "not-a-dict"})
        assert h.feedback_mapping == {}


# ── Cascade dispatch edge case ─────────────────────────────────────────────


class TestCascadeNonJsonResult:
    @pytest.mark.asyncio
    async def test_cascade_skips_non_json_blocking_result(self, hooks_yaml: Path):
        """Cascade dispatch skips hooks whose blocking result is not valid JSON."""
        hook = Hook(
            id="h-001",
            trigger_tool="trig",
            target_tool="tgt",
            server="srv",
            blocking=True,
        )
        reg = HookRegistry(hooks=[hook], settings={"max_depth": 5})
        save(reg, hooks_yaml)

        async def mock_post_hook(*, hook_id, url, target_tool, params):
            return FireResult(
                hook_id=hook_id,
                status_code=200,
                body="ok",
                result="not-valid-json",  # Non-JSON string result
            )

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.tools.fire._resolve_server_url", return_value="unix:///tmp/t.sock"),
            patch("server.tools.fire.post_hook", side_effect=mock_post_hook),
        ):
            result = await hooks_fire("trig", source_result="{}", depth=0)

        data = json.loads(result)
        assert data["hooks_fired"] == 1
        # No cascade errors because the non-JSON is silently skipped
        assert "cascade_errors" not in data
