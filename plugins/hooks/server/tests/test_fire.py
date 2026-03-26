"""Tests for server.tools.fire — fire tool with mocked HTTP."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

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


def _hook(
    hook_id: str,
    trigger: str,
    target: str,
    server: str = "srv",
    *,
    blocking: bool = False,
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
            result = await hooks_fire("trigger_a", _depth=2)

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
            result = await hooks_fire("trigger_a", _depth=3)
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
