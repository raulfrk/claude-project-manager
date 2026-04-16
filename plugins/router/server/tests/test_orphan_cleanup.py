"""Tests for orphan auto-hook removal in discover_and_register."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from server.lib.discovery import discover_and_register
from server.lib.models import Hook, HookRegistry


def _make_default_hooks_file(tmp_path: Path, plugin: str, hooks: list[dict]) -> None:
    """Write a default-hooks.yaml at cache layout for `plugin`."""
    d = tmp_path / plugin / "1.0.0" / ".claude-plugin"
    d.mkdir(parents=True)
    d.joinpath("default-hooks.yaml").write_text(yaml.dump({"hooks": hooks}))


class TestOrphanAutoHookRemoval:
    def test_removes_auto_hook_when_source_file_vanishes(self, tmp_path):
        registry = HookRegistry()
        registry.hooks.append(
            Hook(
                id="sandbox-on-setup",
                trigger_tool="proj_init",
                target_tool="sandbox_batch_setup",
                server="sandbox",
                param_mapping={},
                blocking=True,
                source="auto",
            )
        )
        _make_default_hooks_file(
            tmp_path,
            "proj",
            [{"trigger_tool": "todo_add", "target_tool": "tracking_flush", "server": "proj"}],
        )

        discover_and_register(registry, root=tmp_path, glob_pattern="*/*/.claude-plugin")

        ids = [h.id for h in registry.hooks]
        assert "sandbox-on-setup" not in ids
        assert any(h.server == "proj" for h in registry.hooks)

    def test_preserves_manual_hooks(self, tmp_path):
        registry = HookRegistry()
        registry.hooks.append(
            Hook(
                id="user-custom-hook",
                trigger_tool="todo_complete",
                target_tool="custom_webhook",
                server="external",
                param_mapping={},
                blocking=False,
                source="manual",
            )
        )
        _make_default_hooks_file(
            tmp_path,
            "proj",
            [{"trigger_tool": "todo_add", "target_tool": "tracking_flush", "server": "proj"}],
        )

        discover_and_register(registry, root=tmp_path, glob_pattern="*/*/.claude-plugin")

        ids = [h.id for h in registry.hooks]
        assert "user-custom-hook" in ids

    def test_idempotent_twice(self, tmp_path):
        registry = HookRegistry()
        _make_default_hooks_file(
            tmp_path,
            "proj",
            [{"trigger_tool": "todo_add", "target_tool": "tracking_flush", "server": "proj"}],
        )

        discover_and_register(registry, root=tmp_path, glob_pattern="*/*/.claude-plugin")
        first_state = [(h.id, h.trigger_tool, h.target_tool, h.server) for h in registry.hooks]

        discover_and_register(registry, root=tmp_path, glob_pattern="*/*/.claude-plugin")
        second_state = [(h.id, h.trigger_tool, h.target_tool, h.server) for h in registry.hooks]

        assert first_state == second_state
