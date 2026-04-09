"""Tests for skipped hooks and fire summary fields specific to skip/mix scenarios."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import yaml

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


# ── Skipped hooks ───────────────────────────────────────────────────────────


class TestSkippedHooks:
    """Tests for hooks that are skipped due to false conditions."""

    @pytest.mark.asyncio
    async def test_mixed_fired_and_skipped(self, hooks_yaml: Path, proj_yaml: Path):
        """One hook fires (no condition), one skipped (false condition)."""
        reg = _make_registry(
            [
                _hook("hook-001", "trigger_a", "target_b", blocking=True, condition=None),
                _hook(
                    "hook-002",
                    "trigger_a",
                    "target_c",
                    blocking=True,
                    condition="sync.todoist.enabled",
                ),
            ]
        )
        save(reg, hooks_yaml)

        # todoist disabled
        proj_yaml.write_text(yaml.dump({"sync": {"todoist": {"enabled": False}}}))

        mock_result = FireResult(hook_id="hook-001", status_code=200, body="ok")

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.conditions._PROJ_CONFIG_PATH", proj_yaml),
            patch(
                "server.tools.fire._fire_single", new_callable=AsyncMock, return_value=mock_result
            ),
        ):
            result = await hooks_fire("trigger_a", source_result="{}")

        data = json.loads(result)
        assert data["hooks_fired"] == 1
        assert data["skipped"] == 1
        # Fired hook in results
        assert any(r["hook_id"] == "hook-001" for r in data["results"])
        # Skipped hook in skipped_hooks
        assert len(data["skipped_hooks"]) == 1
        assert data["skipped_hooks"][0]["hook_id"] == "hook-002"
        assert data["skipped_hooks"][0]["target_tool"] == "target_c"

    @pytest.mark.asyncio
    async def test_all_hooks_skipped(self, hooks_yaml: Path, proj_yaml: Path):
        """All matched hooks have false conditions: hooks_fired=0, all in skipped_hooks."""
        reg = _make_registry(
            [
                _hook(
                    "hook-001",
                    "trigger_a",
                    "target_b",
                    blocking=True,
                    condition="sync.todoist.enabled",
                ),
                _hook(
                    "hook-002",
                    "trigger_a",
                    "target_c",
                    blocking=True,
                    condition="sandbox_integration",
                ),
            ]
        )
        save(reg, hooks_yaml)

        # Both conditions false
        proj_yaml.write_text(yaml.dump({"sync": {"todoist": {"enabled": False}}}))

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.conditions._PROJ_CONFIG_PATH", proj_yaml),
        ):
            result = await hooks_fire("trigger_a", source_result="{}")

        data = json.loads(result)
        assert data["hooks_fired"] == 0
        assert data["skipped"] == 2
        assert len(data["skipped_hooks"]) == 2
        hook_ids = {s["hook_id"] for s in data["skipped_hooks"]}
        assert hook_ids == {"hook-001", "hook-002"}
        assert data["errors"] == []

    @pytest.mark.asyncio
    async def test_compound_condition_partial_false_skips(self, hooks_yaml: Path, proj_yaml: Path):
        """Hook with compound 'and' condition skipped when one part is false."""
        reg = _make_registry(
            [
                _hook(
                    "hook-compound",
                    "trigger_a",
                    "target_b",
                    blocking=True,
                    condition="sync.todoist.enabled and sync.todoist.auto_sync",
                ),
            ]
        )
        save(reg, hooks_yaml)

        # enabled=true but auto_sync=false → compound condition false
        proj_yaml.write_text(
            yaml.dump({"sync": {"todoist": {"enabled": True, "auto_sync": False}}})
        )

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.conditions._PROJ_CONFIG_PATH", proj_yaml),
        ):
            result = await hooks_fire("trigger_a", source_result="{}")

        data = json.loads(result)
        assert data["hooks_fired"] == 0
        assert data["skipped"] == 1
        assert data["skipped_hooks"][0]["hook_id"] == "hook-compound"

    @pytest.mark.asyncio
    async def test_missing_proj_yaml_skips_gracefully(self, hooks_yaml: Path, tmp_path: Path):
        """Hook with condition skipped (not errored) when proj.yaml doesn't exist."""
        reg = _make_registry(
            [
                _hook(
                    "hook-001",
                    "trigger_a",
                    "target_b",
                    blocking=True,
                    condition="sync.todoist.enabled",
                ),
            ]
        )
        save(reg, hooks_yaml)

        missing_config = tmp_path / "nonexistent" / "proj.yaml"

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.conditions._PROJ_CONFIG_PATH", missing_config),
        ):
            result = await hooks_fire("trigger_a", source_result="{}")

        data = json.loads(result)
        assert data["hooks_fired"] == 0
        assert data["skipped"] == 1
        assert data["skipped_hooks"][0]["hook_id"] == "hook-001"
        assert data["errors"] == []
